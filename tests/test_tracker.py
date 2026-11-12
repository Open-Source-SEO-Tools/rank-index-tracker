"""Offline unit and loopback integration checks. No external requests or spending."""
import base64
from contextlib import redirect_stdout, redirect_stderr
import copy
import http.client
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import tracker as app


def page(url='https://example.com/pack', name='Feather trail pack', mine=True):
    return {'url': url, 'name': name, 'group': 'Gear', 'mine': mine}


def dataset():
    d = app.empty_data()
    d['pages'] = [page(), page('https://example.org/guide', 'Trail guide', False)]
    d['queries'] = [{'query': 'light trail packs', 'markets': ['us', 'uk']}]
    return d


def snapshot(query='Feather trail pack', results=None, **kwargs):
    s = {'engine': 'bing', 'query': query, 'market': 'us', 'at': '2026-11-10T10:00:00Z', 'results': results or [], 'no_results': False, 'next_page': False, 'challenge': False}
    s.update(kwargs)
    return s


def results(n=3, target=False):
    return [{'rank': i+1, 'url': 'https://example.com/pack' if target and i == 0 else f'https://example.net/trail-{i}', 'title': f'Trail result {i+1}'} for i in range(n)]


def response(keyword='light trail packs', count=4):
    items = [{'type': 'organic', 'rank_group': i+1, 'rank_absolute': i+3, 'url': f'https://example.net/kit-{i}', 'title': f'Kit {i}'} for i in range(count)]
    items.insert(0, {'type': 'paid', 'rank_group': 1, 'rank_absolute': 1, 'url': 'https://example.org/ad'})
    return {'status_code': 20000, 'cost': .002, 'tasks': [{'status_code': 20000, 'cost': .002, 'data': {'keyword': keyword}, 'result': [{'keyword': keyword, 'items': items}]}]}


def run(engine='google', at='2026-11-10T11:00:00Z', rows=None):
    return {'id': 'run-' + engine + at, 'at': at, 'engine': engine, 'market': 'us', 'query': 'light trail packs', 'provider': 'dataforseo-' + engine, 'provider_cost_usd': .002, 'results': rows if rows is not None else results(target=True), 'note': ''}


class IdentityTests(unittest.TestCase):
    def test_scheme_and_trailing_slash_only(self):
        self.assertEqual(app.url_identity('https://example.com/Pack/'), app.url_identity('http://example.com/Pack'))
        self.assertEqual(app.url_identity('https://example.com/'), app.url_identity('http://example.com'))
        self.assertEqual(app.url_identity('https://example.com/Pack/?a=1'), app.url_identity('http://example.com/Pack?a=1'))

    def test_host_www_path_case_queries_ports_fragments_preserved(self):
        for a, b in [('example.com/Pack', 'www.example.com/Pack'), ('example.com/Pack', 'example.com/pack'), ('example.com/Pack?a=1', 'example.com/Pack?a=2'), ('example.com:443/Pack', 'example.com/Pack'), ('example.com/Pack#one', 'example.com/Pack#two'), ('example.com/Pack?', 'example.com/Pack')]:
            with self.subTest(a=a):
                self.assertNotEqual(app.url_identity('https://' + a), app.url_identity('https://' + b))

    def test_unsafe_urls_refused(self):
        for value in ('javascript:alert(1)', 'https://user:pass@example.com/', 'https://', 'https://example.com:bad/', 'https://example.com/a b', None):
            with self.subTest(value=value), self.assertRaises(app.TrackerError):
                app.url_identity(value)

    def test_bing_click_wrapper(self):
        url = 'https://example.com/Pack?kit=light&color=green'
        encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')
        self.assertEqual(app.decode_bing_url('https://www.bing.com/ck/a?x=1&u=a1' + encoded), url)
        self.assertEqual(app.decode_bing_url(url), url)

    def test_bing_malformed_wrappers(self):
        for value in ('', 'a1', 'other', 'a1###', 'a1' + base64.urlsafe_b64encode(b'javascript:alert(1)').decode()):
            with self.subTest(value=value), self.assertRaises(app.TrackerError):
                app.decode_bing_url('https://www.bing.com/ck/a?u=' + value)

    def test_other_host_wrapper_not_decoded(self):
        url = 'https://example.org/ck/a?u=a1aGVsbG8'
        self.assertEqual(app.decode_bing_url(url), url)


class BingTests(unittest.TestCase):
    def classify(self, title=None, url=None):
        return app.classify_bing(page(), 'Feather trail pack', title, url)

    def test_positive_title_match(self):
        r = self.classify(snapshot(results=results(target=True)))
        self.assertIs(r[0], True)
        self.assertEqual(r[3]['match']['rank'], 1)

    def test_positive_url_match(self):
        r = self.classify(None, snapshot('url:https://example.com/pack', results(1, True)))
        self.assertIs(r[0], True)

    def test_negative_pair(self):
        r = self.classify(snapshot(results=results()), snapshot('url:https://example.com/pack', no_results=True))
        self.assertIs(r[0], False)
        self.assertEqual(r[1], 'Not found')

    def test_unknown_missing_both(self):
        self.assertIn('missing', self.classify()[2])
        self.assertIsNone(self.classify()[0])

    def test_unknown_missing_title(self):
        self.assertIn('missing', self.classify(None, snapshot('url:https://example.com/pack', no_results=True))[2])

    def test_unknown_missing_url(self):
        self.assertIn('missing', self.classify(snapshot(results=results()))[2])

    def test_unknown_title_mismatch_even_with_matching_result(self):
        r = self.classify(snapshot('wrong topic', results(3, True)))
        self.assertIsNone(r[0])
        self.assertEqual(r[2], 'Query mismatch')

    def test_unknown_url_mismatch(self):
        self.assertEqual(self.classify(None, snapshot('url:https://example.org/guide'))[2], 'Query mismatch')

    def test_unknown_challenge_each_side(self):
        for a, b in [(snapshot(challenge=True), None), (None, snapshot('url:https://example.com/pack', challenge=True))]:
            with self.subTest(a=a, b=b):
                r = self.classify(a, b)
                self.assertIsNone(r[0])
                self.assertEqual(r[2], 'Challenge page')

    def test_unknown_wrong_market_pair(self):
        r = self.classify(snapshot(results=results()), snapshot('url:https://example.com/pack', no_results=True, market='uk'))
        self.assertIsNone(r[0])
        self.assertIn('markets', r[2])

    def test_unknown_short_title_results(self):
        r = self.classify(snapshot(results=results(2)), snapshot('url:https://example.com/pack', no_results=True))
        self.assertIsNone(r[0])
        self.assertIn('fewer than 3', r[2])

    def test_unknown_unrelated_url_results(self):
        r = self.classify(snapshot(results=results()), snapshot('url:https://example.com/pack', results()))
        self.assertIsNone(r[0])
        self.assertIn('unrelated', r[2])

    def test_unknown_no_explicit_no_results(self):
        r = self.classify(snapshot(results=results()), snapshot('url:https://example.com/pack'))
        self.assertIsNone(r[0])

    def test_unknown_next_page_each_side(self):
        for a, b in [(snapshot(results=results(), next_page=True), snapshot('url:https://example.com/pack', no_results=True)), (snapshot(results=results()), snapshot('url:https://example.com/pack', no_results=True, next_page=True))]:
            r = self.classify(a, b)
            self.assertIsNone(r[0])
            self.assertIn('More results', r[2])

    def test_import_pair_and_derive(self):
        d = dataset()
        app.import_reading(d, snapshot(results=results()))
        self.assertIsNone(d['index_readings'][-1]['indexed'])
        app.import_reading(d, snapshot('url:https://example.com/pack', no_results=True))
        self.assertIs(d['index_readings'][-1]['indexed'], False)
        self.assertEqual(len(d['index_readings']), 2)
        self.assertEqual(app.derive(d)['counts']['bing']['not_indexed'], 1)

    def test_import_pairs_do_not_cross_days_or_markets(self):
        for changed in ({'at':'2026-11-11T10:00:00Z'}, {'market':'uk'}):
            d = dataset()
            app.import_reading(d, snapshot(results=results()))
            app.import_reading(d, snapshot('url:https://example.com/pack', no_results=True, **changed))
            self.assertIsNone(d['index_readings'][-1]['indexed'])

    def test_edited_queue_title_and_mismatch(self):
        d = dataset()
        app.import_reading(d, snapshot('Custom pack title', results(1, True)), 'https://example.com/pack', 'Custom pack title')
        self.assertIs(d['index_readings'][-1]['indexed'], True)
        app.import_reading(d, snapshot('Different query', results(1, True)), 'https://example.com/pack')
        self.assertIsNone(d['index_readings'][-1]['indexed'])
        self.assertIn('mismatch', d['index_readings'][-1]['note'])

    def test_query_mismatch_without_target_rejected(self):
        d = dataset()
        with self.assertRaisesRegex(app.TrackerError, 'mismatch'):
            app.import_reading(d, snapshot('untracked topic'))
        self.assertEqual(d['index_readings'], [])

    def test_browser_rank_import(self):
        d = dataset()
        app.import_reading(d, snapshot('light trail packs', results(3, True)))
        self.assertEqual(d['rank_runs'][-1]['provider'], 'browser-import')
        self.assertEqual(app.derive(d)['counts']['bing']['indexed'], 1)

    def test_rank_import_can_disambiguate_a_page_title(self):
        d = dataset()
        d['pages'][0]['name'] = 'light trail packs'
        app.import_reading(d, snapshot('light trail packs', results(3, True), kind='rank'))
        self.assertEqual(len(d['rank_runs']), 1)
        self.assertEqual(d['index_readings'], [])

    def test_challenge_target_stays_unknown(self):
        d = dataset()
        app.import_reading(d, snapshot(challenge=True, target_url='https://example.com/pack'))
        self.assertIsNone(d['index_readings'][-1]['indexed'])

    def test_import_wrapper_decoded_before_match(self):
        d = dataset()
        encoded = base64.urlsafe_b64encode(b'https://example.com/pack').decode().rstrip('=')
        rows = [{'rank':1, 'title':'Pack', 'url':'https://www.bing.com/ck/a?u=a1'+encoded}]
        app.import_reading(d, snapshot(results=rows))
        self.assertIs(d['index_readings'][-1]['indexed'], True)

    def test_challenge_with_missing_query_box_is_unknown(self):
        d = dataset()
        app.import_reading(d, snapshot('', challenge=True, target_url='https://example.com/pack'))
        self.assertIsNone(d['index_readings'][-1]['indexed'])
        self.assertEqual(d['index_readings'][-1]['note'], 'Challenge page')

    def test_contradictory_snapshot_refused(self):
        with self.assertRaises(app.TrackerError):
            app.normalize_snapshot(snapshot(results=results(), no_results=True))

    def test_ambiguous_title_refused(self):
        d = dataset()
        d['pages'].append(page('https://example.com/other-pack'))
        with self.assertRaisesRegex(app.TrackerError, 'several'):
            app.import_reading(d, snapshot())

    def test_import_does_not_store_unexpected_input_fields(self):
        d = dataset()
        app.import_reading(d, snapshot(unexpected='do not preserve'))
        self.assertNotIn('unexpected', d['index_readings'][-1]['evidence']['snapshot'])


class ProviderTests(unittest.TestCase):
    def test_google_documented_envelope_and_organic_group_rank(self):
        r = app.parse_serp(response(), 'google', 'light trail packs', 'us')
        self.assertEqual(len(r['results']), 4)
        self.assertEqual(r['results'][0]['rank'], 1)
        self.assertEqual(r['provider_cost_usd'], .002)
        self.assertEqual(r['provider'], 'dataforseo-google')

    def test_bing_documented_envelope(self):
        r = app.parse_serp(response(), 'bing', 'light trail packs', 'uk')
        self.assertEqual(r['note'], '')
        self.assertEqual(r['provider'], 'dataforseo-bing')

    def test_bing_suspect_keyword_missing_wrong_or_short(self):
        for payload in (response('different topic'), response(count=2)):
            self.assertEqual(app.parse_serp(payload, 'bing', 'light trail packs', 'us')['note'], 'suspect')
        payload = response()
        del payload['tasks'][0]['result'][0]['keyword']
        self.assertEqual(app.parse_serp(payload, 'bing', 'light trail packs', 'us')['note'], 'suspect')

    def test_google_keyword_mismatch_refused(self):
        with self.assertRaises(app.TrackerError):
            app.parse_serp(response('wrong topic'), 'google', 'light trail packs', 'us')

    def test_empty_items_bing_suspect_google_empty(self):
        payload = response()
        payload['tasks'][0]['result'][0]['items'] = None
        self.assertEqual(app.parse_serp(payload, 'bing', 'light trail packs', 'us')['note'], 'suspect')
        self.assertEqual(app.parse_serp(payload, 'google', 'light trail packs', 'us')['results'], [])

    def test_malformed_provider_responses_refused(self):
        bads = [None, {}, {'status_code':40200}, {'status_code':20000,'tasks':[]}, {'status_code':20000,'tasks':[{'status_code':40200}]}, {'status_code':20000,'tasks':[{'status_code':20000,'result':None}]}]
        for payload in bads:
            with self.subTest(payload=payload), self.assertRaises(app.TrackerError):
                app.parse_serp(payload, 'google', 'light trail packs', 'us')

    def test_invalid_cost_and_duplicate_ranks_refused(self):
        for change in ('cost', 'rank'):
            payload = response()
            if change == 'cost':
                payload['tasks'][0]['cost'] = float('nan')
            else:
                payload['tasks'][0]['result'][0]['items'][-1]['rank_group'] = 1
            with self.assertRaises(app.TrackerError):
                app.parse_serp(payload, 'google', 'light trail packs', 'us')

    def test_google_verdict_mapping(self):
        for verdict in ('PASS', 'FAIL', 'NEUTRAL', 'PARTIAL', 'VERDICT_UNSPECIFIED'):
            r = app.gsc_reading({'inspectionResult':{'indexStatusResult':{'verdict':verdict,'coverageState':'Invented coverage'}}}, 'https://example.com/pack')
            self.assertIs(r['indexed'], verdict == 'PASS')
            self.assertEqual(r['status'], 'Invented coverage')

    def test_google_errors_unknown(self):
        for payload in ({'error':{'code':403}}, {}, {'inspectionResult':None}, {'inspectionResult':{'indexStatusResult':None}}):
            self.assertIsNone(app.gsc_reading(payload, 'https://example.com/pack')['indexed'])

    def test_gsc_property_matching(self):
        self.assertTrue(app.property_contains('sc-domain:example.com', 'https://shop.example.com/pack'))
        self.assertTrue(app.property_contains('https://example.com/gear/', 'https://example.com/gear/pack'))
        for site,url in [('sc-domain:example.com','https://example.org/pack'), ('https://example.com/gear/','https://example.com/gearbox'), ('https://example.com/','http://example.com/pack')]:
            self.assertFalse(app.property_contains(site, url))

    def test_rank_request_contract(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(response()).encode())
        with patch.dict(os.environ, {'DATAFORSEO_LOGIN':'fixture-login','DATAFORSEO_PASSWORD':'fixture-password'}, clear=True), patch.object(app, 'build_opener', return_value=opener) as build:
            app.fetch_rank('google','light trail packs','uk',20)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, app.API.format('google'))
        self.assertEqual(json.loads(req.data), [{'keyword':'light trail packs','location_code':2826,'language_code':'en','device':'desktop','depth':20}])
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[2], app.NoRedirect)
        self.assertIsNone(app.NoRedirect().redirect_request(req,None,302,'',{},'https://example.org/'))

    def test_no_paid_retry_and_errors_do_not_leak(self):
        for failure in (HTTPError(app.API.format('google'),401,'sensitive detail',{},None), URLError('sensitive detail'), TimeoutError()):
            opener=Mock();opener.open.side_effect=failure
            with patch.object(app,'build_opener',return_value=opener), self.assertRaises(app.TrackerError) as error:
                app.request_bytes(app.API.format('google'), b'[]')
            self.assertNotIn('sensitive',str(error.exception))
            self.assertEqual(opener.open.call_count,1)

    def test_https_and_response_cap(self):
        with self.assertRaises(app.TrackerError):
            app.request_bytes('http://example.com/')
        opener=Mock();opener.open.return_value=io.BytesIO(b'12345')
        with patch.object(app,'build_opener',return_value=opener), self.assertRaises(app.TrackerError):
            app.request_bytes('https://example.com/',limit=4)

    def test_refresh_token_form_contract(self):
        env={'GSC_CLIENT_ID':'fixture-id','GSC_CLIENT_SECRET':'fixture-secret','GSC_REFRESH_TOKEN':'fixture-refresh'}
        with patch.dict(os.environ,env,clear=True), patch.object(app,'request_bytes',return_value=b'{"access_token":"fixture-token"}') as req:
            self.assertEqual(app.gsc_token(),'fixture-token')
        self.assertEqual(req.call_args.args[0],app.TOKEN_API)
        self.assertIn(b'grant_type=refresh_token',req.call_args.args[1])
        self.assertEqual(req.call_args.args[2]['Content-Type'],'application/x-www-form-urlencoded')

    def test_access_token_needs_no_refresh_request(self):
        with patch.dict(os.environ,{'GSC_ACCESS_TOKEN':'fixture-token'},clear=True), patch.object(app,'request_bytes') as req:
            self.assertEqual(app.gsc_token(),'fixture-token')
            req.assert_not_called()


class StorageAndCLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=app.ROOT)
        self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name)/'private'

    def cli(self, *args):
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
            code=app.main(['--data-dir',str(self.dir),*args])
        return code,output.getvalue(),error.getvalue()

    def save(self,d=None):
        self.dir.mkdir(exist_ok=True)
        app.save_dataset(self.dir/'tracker.json',d or dataset())

    def test_preview_rank_no_network_no_files_no_credentials(self):
        with patch.dict(os.environ,{},clear=True), patch.object(app,'request_bytes') as req:
            code,out,_=self.cli('rank','--engine','google','--query','trail packs')
            self.assertEqual(code,0)
            self.assertIn('1 paid requests',out)
            self.assertIn('0.002000',out)
            req.assert_not_called()
        self.assertFalse(self.dir.exists())

    def test_preview_existing_dataset_unchanged_and_job_count(self):
        self.save();before=(self.dir/'tracker.json').read_bytes()
        with patch.object(app,'request_bytes') as req:
            code,out,_=self.cli('rank','--engine','bing','--depth','30')
            self.assertEqual(code,0)
            self.assertIn('2 paid requests',out)
            self.assertIn('0.012000',out)
            req.assert_not_called()
        self.assertEqual((self.dir/'tracker.json').read_bytes(),before)

    def test_preview_index_no_files_or_network(self):
        with patch.object(app,'request_bytes') as req:
            code,out,_=self.cli('index','--engine','google')
            self.assertEqual(code,0)
            self.assertIn('Preview only',out)
            req.assert_not_called()
        self.assertFalse(self.dir.exists())

    def test_missing_credentials_preserve_data_exit_two(self):
        self.save();before=(self.dir/'tracker.json').read_bytes()
        with patch.dict(os.environ,{},clear=True),patch.object(app,'request_bytes') as req:
            for args in [('rank','--engine','google','--spend'),('rank','--engine','bing','--spend'),('index','--engine','google','--run','--site-url','sc-domain:example.com')]:
                self.assertEqual(self.cli(*args)[0],2)
                self.assertEqual((self.dir/'tracker.json').read_bytes(),before)
            req.assert_not_called()

    def test_operators_refused_before_network(self):
        for q in ('site:example.com packs','INTITLE:pack','inurl : gear','filetype:pdf','cache:example.com','url:https://example.com','newoperator:value'):
            with self.subTest(q=q),patch.object(app,'fetch_rank') as fetch:
                code,_,_=self.cli('rank','--engine','google','--query',q,'--spend')
                self.assertEqual(code,2)
                fetch.assert_not_called()
        self.assertFalse(self.dir.exists())

    def test_add_remove_pages_queries_history_kept(self):
        self.assertEqual(self.cli('add-page','https://example.com/pack','--name','Pack')[0],0)
        self.assertEqual(self.cli('add-page','http://example.com/pack/')[0],0)
        self.assertEqual(len(app.load_mine(self.dir)['pages']),1)
        self.assertEqual(self.cli('add-query','trail packs','--market','us,uk')[0],0)
        self.assertEqual(self.cli('remove-query','trail packs')[0],0)
        self.assertEqual(self.cli('remove-page','http://example.com/pack')[0],0)
        self.assertEqual(app.load_mine(self.dir)['pages'],[])

    def test_provider_failure_preserves_original(self):
        self.save();before=(self.dir/'tracker.json').read_bytes()
        with patch.dict(os.environ,{'DATAFORSEO_LOGIN':'fixture','DATAFORSEO_PASSWORD':'fixture'}), patch.object(app,'fetch_rank',side_effect=app.TrackerError('Fixture failure')):
            self.assertEqual(self.cli('rank','--engine','google','--spend')[0],2)
        self.assertEqual((self.dir/'tracker.json').read_bytes(),before)
        self.assertFalse((self.dir/'.tracker.lock').exists())

    def test_partial_batch_recovery_original_preserved(self):
        self.save();before=(self.dir/'tracker.json').read_bytes()
        with patch.dict(os.environ,{'DATAFORSEO_LOGIN':'fixture','DATAFORSEO_PASSWORD':'fixture'}), patch.object(app,'fetch_rank',side_effect=[run(),app.TrackerError('Fixture failure')]):
            self.assertEqual(self.cli('rank','--engine','google','--spend')[0],2)
        self.assertEqual((self.dir/'tracker.json').read_bytes(),before)
        files=list(self.dir.glob('recovery-*.json'))
        self.assertEqual(len(files),1)
        self.assertEqual(len(app.read_dataset(files[0])['rank_runs']),1)

    def test_inspection_owned_only_limit_and_unknown_error(self):
        self.save()
        with patch.dict(os.environ,{'GSC_ACCESS_TOKEN':'fixture'},clear=True),patch.object(app,'json_request',side_effect=app.TrackerError('Provider HTTP 403.')) as req:
            self.assertEqual(self.cli('index','--engine','google','--site-url','sc-domain:example.com','--limit','1','--run')[0],0)
        self.assertEqual(req.call_count,1)
        r=app.load_mine(self.dir)['index_readings'][0]
        self.assertIsNone(r['indexed'])
        self.assertIn('403',r['note'])

    def test_atomic_replace_and_cleanup(self):
        self.save();path=self.dir/'tracker.json';before=path.read_bytes()
        with patch.object(app.os,'replace',side_effect=OSError('Fixture failure')),self.assertRaises(OSError):
            app.save_dataset(path,dataset())
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(list(self.dir.glob('.tracker-*')),[])
        app.save_dataset(path,app.empty_data())
        self.assertEqual(app.read_dataset(path)['pages'],[])

    def test_writer_lock_exclusive_and_cleanup(self):
        with app.writer(self.dir):
            self.assertTrue((self.dir/'.tracker.lock').exists())
            with self.assertRaises(app.TrackerError):
                with app.writer(self.dir):
                    self.fail('Second writer acquired lock')
        self.assertFalse((self.dir/'.tracker.lock').exists())
        with self.assertRaises(ValueError):
            with app.writer(self.dir):
                raise ValueError('fixture')
        self.assertFalse((self.dir/'.tracker.lock').exists())

    def test_lock_or_invalid_data_prevents_spending(self):
        self.save()
        with patch.dict(os.environ,{'DATAFORSEO_LOGIN':'fixture','DATAFORSEO_PASSWORD':'fixture'}), patch.object(app,'fetch_rank') as fetch:
            with app.writer(self.dir):
                self.assertEqual(self.cli('rank','--engine','google','--spend')[0],2)
            (self.dir/'tracker.json').write_text('broken')
            self.assertEqual(self.cli('rank','--engine','google','--spend')[0],2)
            fetch.assert_not_called()

    def test_export_json_csv_no_writes(self):
        self.save()
        self.assertEqual(self.cli('export')[0],0)
        self.assertIn('type,at_utc',self.cli('export','--format','csv')[1])

    def test_formula_csv_escaped(self):
        d=dataset();r=run();r['query']='=invented formula';d['rank_runs'].append(r)
        raw,_=app.export_data(d,'csv')
        self.assertIn(b"'=invented formula",raw)

    def test_size_limit_and_invalid_json(self):
        self.dir.mkdir()
        path=self.dir/'tracker.json';path.write_bytes(b'not-json')
        with self.assertRaises(app.TrackerError): app.read_dataset(path)
        path.write_bytes(b' ' * 20)
        with patch.object(app,'MAX_BYTES',10),self.assertRaises(app.TrackerError):app.read_dataset(path)
        with self.assertRaises(app.TrackerError):app.decode_json(b'{"x": NaN}')


class DerivedAndSchemaTests(unittest.TestCase):
    def test_demo_schema_counts_history_and_sources(self):
        d=app.read_dataset(app.ROOT/'demo.json');derived=app.derive(d)
        self.assertEqual(len(d['pages']),40)
        self.assertEqual(len(d['queries']),6)
        self.assertEqual(len(d['rank_runs']),336)
        self.assertTrue(all(len(h['runs'])==14 for h in derived['rank_history']))
        self.assertEqual(derived['counts']['google']['indexed'],31)
        self.assertEqual(derived['counts']['bing']['indexed'],24)
        self.assertEqual(derived['counts']['google']['unknown'],4)
        self.assertEqual(derived['counts']['bing']['unknown'],8)
        self.assertTrue(any(r['note']=='suspect' for r in d['rank_runs']))

    def test_seen_ranking_latest_first_and_unique_top_ten(self):
        d=dataset()
        earlier=app.gsc_reading({'inspectionResult':{'indexStatusResult':{'verdict':'PASS'}}},d['pages'][0]['url'])
        earlier['at']='2026-11-02T00:00:00Z';d['index_readings'].append(earlier)
        d['rank_runs'].append(run(rows=[{'rank':1,'url':'http://example.com/pack/','title':'Pack'},{'rank':2,'url':'https://example.com/pack','title':'Same pack'},{'rank':3,'url':'https://example.org/guide','title':'Not mine'}]))
        derived=app.derive(d);r=derived['pages'][0]['engines']['google']
        self.assertEqual(r['first_indexed'],'2026-11-02T00:00:00Z')
        self.assertEqual(r['provider'],'rank-run')
        self.assertIn('seen ranking',r['status'])
        self.assertEqual(derived['rank_history'][0]['runs'][0]['top10_yours'],1)
        self.assertEqual(derived['rank_history'][0]['runs'][0]['best_rank'],1)
        self.assertEqual(derived['counts']['google']['indexed'],2)

    def test_unknown_is_not_negative(self):
        derived=app.derive(dataset())
        self.assertEqual(derived['counts']['google']['not_indexed'],0)
        self.assertEqual(derived['counts']['google']['unknown'],2)

    def test_later_unknown_supersedes_older_positive(self):
        d=dataset();d['rank_runs'].append(run())
        r=app.gsc_reading({},d['pages'][0]['url']);r['at']='2026-11-11T00:00:00Z';d['index_readings'].append(r)
        row=app.derive(d)['pages'][0]['engines']['google']
        self.assertIsNone(row['indexed'])
        self.assertEqual(row['first_indexed'],'2026-11-10T11:00:00Z')

    def test_suspect_bing_not_positive_index_evidence(self):
        d=dataset();r=run('bing');r['note']='suspect';d['rank_runs'].append(r)
        self.assertEqual(app.derive(d)['counts']['bing']['indexed'],0)

    def test_schema_rejects_malformed_structures(self):
        mutations=[lambda d:d.update(pages=None),lambda d:d['pages'][0].update(mine=1),lambda d:d['queries'][0].update(markets=[[]]),lambda d:d['pages'].append(copy.deepcopy(d['pages'][0])),lambda d:d.update(schema_version=True),lambda d:d.update(unexpected='extra')]
        for mutation in mutations:
            d=dataset();mutation(d)
            with self.subTest(mutation=mutation),self.assertRaises(app.TrackerError):app.validate_dataset(d)

    def test_utc_and_record_validation(self):
        for changes in ({'at':'2026-11-01T00:00:00'},{'at':'2026-11-01T00:00:00+03:00'},{'engine':[]},{'provider':[]},{'market':[]},{'provider_cost_usd':True}):
            d=dataset();r=run();r.update(changes);d['rank_runs'].append(r)
            with self.subTest(changes=changes),self.assertRaises(app.TrackerError):app.validate_dataset(d)

    def test_limits(self):
        d=dataset()
        with patch.object(app,'MAX_PAGES',1),self.assertRaises(app.TrackerError):app.validate_dataset(d)

    def test_sitemap_namespaces_and_url_cap(self):
        raw=b'<urlset xmlns="https://example.org/sitemap"><url><loc>https://example.com/one</loc></url><url><loc>https://example.com/two</loc></url></urlset>'
        self.assertEqual(len(app.parse_sitemap(raw)),2)
        with patch.object(app,'MAX_PAGES',1),self.assertRaisesRegex(app.TrackerError,'cap'):app.parse_sitemap(raw)

    def test_sitemap_entities_dtd_and_utf16_refused(self):
        xml='<!DOCTYPE urlset [<!ENTITY x "https://example.com/">]><urlset><url><loc>&x;</loc></url></urlset>'
        for raw in (xml.encode(),xml.encode('utf-16'),xml.encode('utf-32')):
            with self.assertRaisesRegex(app.TrackerError,'disabled'):app.parse_sitemap(raw)

    def test_sitemap_invalid_index_and_size_refused(self):
        for raw in (b'<broken',b'<sitemapindex/>',b'<urlset><url><loc>javascript:alert(1)</loc></url></urlset>',b' '*2000001):
            with self.assertRaises(app.TrackerError):app.parse_sitemap(raw)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=app.ROOT)
        cls.directory=Path(cls.temp.name)
        app.save_dataset(cls.directory/'tracker.json',dataset())
        cls.server=app.make_server(cls.directory,0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.port=cls.server.server_port
        conn=http.client.HTTPConnection('127.0.0.1',cls.port)
        conn.request('GET','/')
        cls.html=conn.getresponse().read().decode();conn.close()
        cls.token=re.search(r'name="import-token" content="([^"]+)"',cls.html).group(1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def request(self,method,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        conn.request(method,path,body=body,headers=headers or {})
        response=conn.getresponse();result=(response.status,dict(response.getheaders()),response.read());conn.close();return result

    def post(self,headers=None,path='/api/import-reading?source=mine',raw=None):
        h={'Content-Type':'application/json','X-Import-Token':self.token};h.update(headers or {})
        return self.request('POST',path,json.dumps(raw or snapshot()).encode(),h)

    def test_binds_only_loopback(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')

    def test_ui_and_demo_json_security_headers(self):
        status,headers,body=self.request('GET','/')
        self.assertEqual(status,200);self.assertNotIn(b'__IMPORT_TOKEN__',body)
        self.assertIn("default-src 'self'",headers['Content-Security-Policy'])
        self.assertNotIn('unsafe-inline',headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(headers['Referrer-Policy'],'no-referrer')
        status,_,body=self.request('GET','/api/data?source=demo')
        self.assertEqual(status,200);self.assertEqual(len(json.loads(body)['pages']),40)

    def test_missing_token_rejected(self):self.assertEqual(self.post({'X-Import-Token':''})[0],403)
    def test_wrong_host_rejected(self):self.assertEqual(self.post({'Host':'example.org'})[0],403)
    def test_wrong_origin_rejected(self):self.assertEqual(self.post({'Origin':'https://example.org'})[0],403)
    def test_demo_write_rejected(self):self.assertEqual(self.post(path='/api/import-reading?source=demo')[0],403)
    def test_wrong_content_type_rejected(self):self.assertEqual(self.post({'Content-Type':'text/plain'})[0],415)
    def test_oversized_body_rejected(self):self.assertEqual(self.post({'Content-Length':str(app.IMPORT_BYTES+1)})[0],413)

    def test_valid_import_and_export(self):
        self.assertEqual(self.post({'Origin':f'http://127.0.0.1:{self.port}'})[0],200)
        for fmt in ('json','csv'):
            status,headers,body=self.request('GET','/api/export?source=mine&format='+fmt)
            self.assertEqual(status,200);self.assertIn('attachment',headers['Content-Disposition'])
            if fmt=='json':app.validate_dataset(json.loads(body))

    def test_malformed_json_preserves_file(self):
        before=(self.directory/'tracker.json').read_bytes()
        status,_,_=self.request('POST','/api/import-reading?source=mine',b'{broken',{'Content-Type':'application/json','X-Import-Token':self.token})
        self.assertEqual(status,422);self.assertEqual((self.directory/'tracker.json').read_bytes(),before)

    def test_corrupt_schema_ui_error_server_survives(self):
        path=self.directory/'tracker.json';before=path.read_bytes()
        try:
            path.write_text('{"schema_version":1,"pages":{},"queries":[],"rank_runs":[],"index_readings":[]}')
            status,_,body=self.request('GET','/api/data?source=mine')
            self.assertEqual(status,422);self.assertIn('error',json.loads(body))
            self.assertEqual(self.request('GET','/')[0],200)
        finally:path.write_bytes(before)

    def test_static_allowlist(self):
        for path in ('/tracker.py','/../LICENSE','/demo.json','/private-data/tracker.json'):
            self.assertEqual(self.request('GET',path)[0],404)
        self.assertEqual(self.request('GET','/bing-snippet.js')[0],200)

    def test_no_environment_credentials_in_browser(self):
        with patch.dict(os.environ,{'GSC_ACCESS_TOKEN':'fixture-secret-value'}):
            self.assertNotIn(b'fixture-secret-value',self.request('GET','/')[2])
            self.assertNotIn(b'fixture-secret-value',self.request('GET','/api/data?source=mine')[2])


class RepositoryChecks(unittest.TestCase):
    def test_no_em_dash_or_unapproved_hostnames(self):
        # Real hosts are allowed only for provider docs/API, Bing searches, the clone URL,
        # and the W3C SVG namespace (an identifier, never a remote request).
        allowed={'dataforseo.com','docs.dataforseo.com','api.dataforseo.com','developers.google.com','searchconsole.googleapis.com','oauth2.googleapis.com','www.googleapis.com','www.bing.com','bing.com','github.com','www.w3.org','localhost'}
        suffixes=('example.com','example.org','example.net')
        files=[p for p in app.ROOT.rglob('*') if p.is_file() and not any(part.startswith('.') or part=='__pycache__' or part.startswith('tmp') for part in p.relative_to(app.ROOT).parts)]
        # Dotfiles relevant to distribution are scanned explicitly without reading credentials.
        files.append(app.ROOT/'.gitignore')
        for p in files:
            raw=p.read_text(encoding='utf-8')
            self.assertNotIn(chr(0x2014),raw,str(p.relative_to(app.ROOT)))
            hosts=set(re.findall(r'\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|org|net|io|dev|au|pro|co|app|ai|edu|gov)\b',raw,re.I))
            for host in hosts:
                host=host.lower()
                self.assertTrue(host in allowed or any(host==s or host.endswith('.'+s) for s in suffixes),f'{p.relative_to(app.ROOT)}: {host}')


if __name__=='__main__':
    unittest.main()
