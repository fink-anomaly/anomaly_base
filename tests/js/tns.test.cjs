const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourcePath = path.resolve(__dirname, '../../src/anomaly/static/assets/js/tns.js');
const source = fs.readFileSync(sourcePath, 'utf8');

function response(data, status = 200) {
    return {ok: status < 400, status, async json() {return data;}};
}

// Only browser boundaries are simulated; every test executes the shipped JS.
async function page({environment = 'sandbox', configStatus = 200, submit, status,
                     storageFails = false, valid = true} = {}) {
    const ids = ['tns-form', 'tns-submit', 'tns-result', 'tns-feedback', 'tns-report-id',
        'tns-check', 'tns-confirm', 'tns-destination', 'tns-environment', 'tns-status-form'];
    const elements = Object.fromEntries(ids.map(id => [id, {
        value: '', textContent: '', checked: true, disabled: false, listeners: {},
        addEventListener(name, callback) {this.listeners[name] = callback;}
    }]));
    const form = elements['tns-form'];
    form.dataset = {user: 'reporter'};
    form.elements = {object_id: {value: 'ZTF17aabvfza'}};
    form.reportValidity = () => valid;
    const calls = [], timers = [], storage = new Map([['tns-receipt:reporter:sandbox', '21']]);
    const context = vm.createContext({
        document: {getElementById(id) {assert.ok(elements[id], id); return elements[id];}},
        token_: 'Bearer fake-test-token',
        FormData: class {constructor(input) {this.object_id = input.elements.object_id.value;}},
        sessionStorage: {
            getItem(key) {if (storageFails) throw new Error('storage denied'); return storage.get(key);},
            setItem(key, value) {if (storageFails) throw new Error('storage denied'); storage.set(key, value);}
        },
        setTimeout(callback, delay) {timers.push(delay); callback();},
        fetch: async (url, options) => {
            calls.push({url, options});
            if (url === '/user/tns/config') return response(configStatus === 200 ? {environment} : {detail: 'Not configured'}, configStatus);
            if (url === '/user/submitTNS') return submit ? submit() : response({report_id: 42, environment, status: 'pending'}, 202);
            return status ? status() : response({report_id: 42, environment, status: 'submitted', feedback: {message: '<script>test</script>'}});
        }
    });
    vm.runInContext(source, context, {filename: sourcePath});
    await new Promise(setImmediate);
    return {elements, calls, timers, storage,
        async send() {await form.listeners.submit({preventDefault() {}});},
        async check() {await elements['tns-status-form'].listeners.submit({preventDefault() {}});},
        posts() {return calls.filter(call => call.url === '/user/submitTNS');}
    };
}

test('initialization restores only this account/environment receipt and hides secrets', async () => {
    const p = await page();
    assert.equal(p.elements['tns-report-id'].value, '21');
    assert.equal(p.elements['tns-destination'].value, 'sandbox');
    assert.equal(p.elements['tns-submit'].disabled, false);
    assert.match(p.elements['tns-environment'].textContent, /sandbox/);
    assert.equal(p.calls[0].options.headers.Authorization, 'Bearer fake-test-token');
});

test('production destination is explicit and does not restore sandbox receipts', async () => {
    const p = await page({environment: 'production'});
    assert.match(p.elements['tns-environment'].textContent, /PRODUCTION/);
    assert.equal(p.elements['tns-destination'].value, 'production');
    assert.equal(p.elements['tns-report-id'].value, '');
});

test('configuration errors disable sending', async () => {
    const p = await page({configStatus: 503});
    await p.send();
    assert.equal(p.elements['tns-submit'].disabled, true);
    assert.match(p.elements['tns-environment'].textContent, /Not configured/);
    assert.equal(p.posts().length, 0);
});

test('invalid form does not submit', async () => {
    const p = await page({valid: false});
    await p.send();
    assert.equal(p.posts().length, 0);
});

test('receipt is saved before feedback; success does not permit duplicate POST', async () => {
    const p = await page();
    await p.send();
    assert.equal(p.posts().length, 1);
    assert.equal(p.posts()[0].options.body.object_id, 'ZTF17aabvfza');
    assert.equal(p.storage.get('tns-receipt:reporter:sandbox'), '42');
    assert.match(p.elements['tns-result'].textContent, /confirms/);
    assert.match(p.elements['tns-feedback'].textContent, /<script>test<\/script>/);
    assert.equal(p.elements['tns-confirm'].checked, false);
    await p.send();
    assert.equal(p.posts().length, 1);
    assert.match(p.elements['tns-result'].textContent, /already has a submission attempt/);
});

test('pending feedback is polled at most ten times, preserving the receipt', async () => {
    const p = await page({status: () => response({report_id: 42, environment: 'sandbox', status: 'pending'})});
    await p.send();
    assert.equal(p.posts().length, 1);
    assert.equal(p.calls.filter(call => call.url.includes('/reports/')).length, 10);
    assert.deepEqual(p.timers, Array(10).fill(3000));
    assert.match(p.elements['tns-result'].textContent, /Check status later/);
});

test('definitive rejection permits corrected manual submission', async () => {
    const p = await page({status: () => response({report_id: 42, environment: 'sandbox', status: 'rejected'})});
    await p.send();
    assert.match(p.elements['tns-result'].textContent, /rejected/);
    await p.send();
    assert.equal(p.posts().length, 2);
});

test('unclassified feedback does not claim success', async () => {
    const p = await page({status: () => response({report_id: 42, environment: 'sandbox', status: 'review'})});
    await p.send();
    assert.match(p.elements['tns-result'].textContent, /not confirmed/);
});

for (const code of [403, 409, 422, 503]) {
    test(`definite pre-submission HTTP ${code} permits a manual retry`, async () => {
        const p = await page({submit: () => response({detail: 'Rejected before submission'}, code)});
        await p.send(); await p.send();
        assert.equal(p.posts().length, 2);
        assert.equal(p.elements['tns-submit'].disabled, false);
    });
}

for (const failure of ['network', 'non-json', 'http-502']) {
    test(`ambiguous ${failure} error never retries the submission`, async () => {
        const p = await page({submit: () => {
            if (failure === 'network') throw new Error('Lost connection');
            if (failure === 'non-json') return {ok: false, status: 502, json: async () => {throw new Error('Invalid JSON');}};
            return response({detail: 'Unknown outcome'}, 502);
        }});
        await p.send();
        assert.match(p.elements['tns-result'].textContent, /no automatic retry/);
        await p.send();
        assert.equal(p.posts().length, 1);
    });
}

test('HTTP 503 while polling cannot unlock an already received submission', async () => {
    const p = await page({status: () => response({detail: 'Configuration disappeared'}, 503)});
    await p.send(); await p.send();
    assert.equal(p.posts().length, 1);
    assert.equal(p.elements['tns-report-id'].value, 42);
});

test('unavailable storage cannot prevent receipt display or submission', async () => {
    const p = await page({storageFails: true});
    await p.send();
    assert.equal(p.elements['tns-report-id'].value, 42);
    assert.match(p.elements['tns-result'].textContent, /confirms/);
});

test('manual status checks never send another report and recover after errors', async () => {
    const p = await page({status: () => response({detail: [{msg: 'Unavailable'}]}, 502)});
    await p.check();
    assert.match(p.elements['tns-result'].textContent, /Could not check this report/);
    assert.equal(p.elements['tns-check'].disabled, false);
    assert.equal(p.posts().length, 0);
    assert.equal(p.calls.at(-1).url, '/user/tns/reports/21');
});

test('concurrent submit and manual-check events do not create additional requests', async () => {
    let finish;
    const p = await page({submit: () => new Promise(resolve => {finish = resolve;})});
    const first = p.send();
    await p.send(); await p.check();
    assert.equal(p.posts().length, 1);
    assert.equal(p.calls.filter(call => call.url.includes('/reports/')).length, 0);
    finish(response({report_id: 42, environment: 'sandbox', status: 'pending'}, 202));
    await first;
    assert.match(p.elements['tns-result'].textContent, /confirms/);
});

test('unknown processing status is shown without inventing success', async () => {
    const p = await page({status: () => response({report_id: 42, environment: 'sandbox', status: 'future-state'})});
    await p.send();
    assert.match(p.elements['tns-result'].textContent, /Unknown result/);
    assert.equal(p.posts().length, 1);
});

test('HTTP errors without a detail use the status code', async () => {
    const p = await page({submit: () => response({}, 502)});
    await p.send();
    assert.match(p.elements['tns-result'].textContent, /Request failed \(502\)/);
});

test('successful manual receipt lookup confirms status without submitting', async () => {
    const p = await page();
    await p.check();
    assert.match(p.elements['tns-result'].textContent, /confirms/);
    assert.equal(p.elements['tns-check'].disabled, false);
    assert.equal(p.posts().length, 0);
});
