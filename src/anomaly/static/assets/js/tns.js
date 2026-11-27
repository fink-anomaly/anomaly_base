/* A TNS receipt is persisted before polling; retries only retrieve feedback. */
(() => {
    const form = document.getElementById('tns-form');
    const send = document.getElementById('tns-submit');
    const result = document.getElementById('tns-result');
    const feedback = document.getElementById('tns-feedback');
    const receipt = document.getElementById('tns-report-id');
    const check = document.getElementById('tns-check');
    let environment;
    let busy = false;
    const sentObjects = new Set();
    let storageKey;

    function remember(reportId) {
        // Storage can be disabled by the browser. The receipt must still be
        // displayed and usable when that happens.
        try { sessionStorage.setItem(storageKey, String(reportId)); } catch (_) { /* optional */ }
    }

    async function request(url, options = {}) {
        const response = await fetch(url, {
            ...options, headers: {'Authorization': token_, ...options.headers}
        });
        const data = await response.json();
        if (!response.ok) {
            const message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
            const error = new Error(message || `Request failed (${response.status})`);
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function show(data) {
        feedback.textContent = data.feedback ? JSON.stringify(data.feedback, null, 2) : '';
        const messages = {
            pending: 'Received by TNS; processing is pending.',
            submitted: 'TNS confirms the discovery report was submitted.',
            rejected: 'TNS rejected the report. Review the feedback before correcting it.',
            review: 'TNS returned feedback requiring review; submission is not confirmed.'
        };
        result.textContent = `${data.environment}: report ${data.report_id}. ${messages[data.status] || 'Unknown result.'}`;
    }

    async function checkStatus(reportId) {
        const data = await request(`/user/tns/reports/${encodeURIComponent(reportId)}`);
        show(data);
        return data.status;
    }

    async function initialize() {
        try {
            const config = await request('/user/tns/config');
            environment = config.environment;
            document.getElementById('tns-destination').value = environment;
            storageKey = `tns-receipt:${form.dataset.user}:${environment}`;
            try { receipt.value = sessionStorage.getItem(storageKey) || ''; } catch (_) { /* optional */ }
            document.getElementById('tns-environment').textContent = environment === 'production'
                ? 'Destination: TNS PRODUCTION. A successful report is published on the real TNS.'
                : 'Destination: TNS sandbox (test environment).';
            send.disabled = false;
        } catch (error) {
            document.getElementById('tns-environment').textContent = error.message;
            send.disabled = true;
        }
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (busy || !environment || !form.reportValidity()) return;
        const objectId = form.elements.object_id.value;
        if (sentObjects.has(objectId)) {
            result.textContent = 'This object already has a submission attempt in this page. Check its report status or TNS before resubmitting.';
            return;
        }
        busy = true;
        send.disabled = true;
        result.textContent = 'Sending report...';
        feedback.textContent = '';
        // Even a lost HTTP response can follow a successful submission. Do not
        // automatically send another copy after any ambiguous failure.
        sentObjects.add(objectId);
        let hasReceipt = false;
        try {
            const data = await request('/user/submitTNS', {method: 'POST', body: new FormData(form)});
            hasReceipt = true;
            receipt.value = data.report_id;
            remember(data.report_id);
            show(data);
            for (let attempt = 0; attempt < 10; attempt++) {
                await new Promise(resolve => setTimeout(resolve, 3000));
                const status = await checkStatus(data.report_id);
                if (status === 'rejected') sentObjects.delete(objectId);
                if (status !== 'pending') return;
            }
            result.textContent += ' Keep this report ID and use Check status later; do not submit another copy.';
        } catch (error) {
            if (!hasReceipt && [403, 409, 422, 503].includes(error.status)) sentObjects.delete(objectId);
            result.textContent = `Error: ${error.message} Check TNS before resubmitting; no automatic retry was made.`;
        } finally {
            busy = false;
            send.disabled = false;
            document.getElementById('tns-confirm').checked = false;
        }
    });

    document.getElementById('tns-status-form').addEventListener('submit', async event => {
        event.preventDefault();
        if (busy) return;
        busy = true;
        check.disabled = true;
        try {
            await checkStatus(receipt.value);
        } catch (error) {
            result.textContent = `Could not check this report: ${error.message} Keep the report ID and check again later.`;
        } finally {
            busy = false;
            check.disabled = false;
        }
    });
    initialize();
})();
