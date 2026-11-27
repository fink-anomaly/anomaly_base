/*
	Astral by HTML5 UP
	html5up.net | @ajlkn
	Free for personal and commercial use under the CCA 3.0 license (html5up.net/license)
*/

(() => {
	const main = document.getElementById('main');
	if (!main) return;
	const panels = [...main.querySelectorAll(':scope > .panel')];
	const navLinks = document.querySelectorAll('#nav > a');

	function showPanel() {
		const requestedId = window.location.hash.slice(1);
		const selected = panels.find((panel) => panel.id === requestedId)
			|| document.getElementById(main.dataset.defaultPanel) || panels[0];
		panels.forEach((panel) => { panel.hidden = panel !== selected; });
		navLinks.forEach((link) => {
			const active = link.hash === '#' + selected.id;
			link.classList.toggle('active', active);
			if (active) link.setAttribute('aria-current', 'page');
			else link.removeAttribute('aria-current');
		});
		window.scrollTo(0, 0);
	}

	window.addEventListener('hashchange', showPanel);
	showPanel();
	document.body.classList.remove('is-preload');

	const tiles = document.getElementById('tiles');
	if (!tiles) return;
	const notificationStatus = document.getElementById('notification-status');
	const notificationPreview = document.getElementById('notification-preview');

	tiles.addEventListener('click', async (event) => {
		const button = event.target.closest('button');
		if (!button) return;

		const tile = button.closest('.tile');
		const {id, ztfId, candidId} = tile.dataset;
		const {tag, action} = button.dataset;
		if (button.classList.contains('tile-preview')) {
			const source = button.querySelector('img');
			const preview = notificationPreview.querySelector('img');
			preview.src = source.currentSrc || source.src;
			preview.alt = source.alt;
			notificationPreview.showModal();
			return;
		}
		if (action === 'tns') {
			document.getElementById('object_id').value = ztfId;
			document.getElementById('remarks').value = 'Data provided by ZTF and processed by Fink';
			window.location.hash = '#TNS';
			return;
		}
		if (!tag && action !== 'remove') return;

		const status = tile.querySelector('.tile-status');
		const buttons = [...tile.querySelectorAll('.tile-actions button')];
		buttons.forEach((control) => { control.disabled = true; });
		let savedTag = tile.dataset.savedTag;
		status.textContent = tag ? 'Saving label…' : 'Removing notification…';
		try {
			if (tag) {
				if (!await saveReaction(ztfId, candidId || null, tag)) throw new Error();
				tile.dataset.savedTag = savedTag = tag;
			}
			const response = await fetch(`/images/${encodeURIComponent(id)}`, {
				method: 'DELETE', headers: {'Authorization': token_}
			});
			if (!response.ok && response.status !== 404) throw new Error();
		} catch {
			status.textContent = savedTag ? 'Label saved. Could not remove the notification. Retry removal.'
				: tag ? 'Could not save the label. Try again.' : 'Could not remove the notification. Try again.';
			buttons.forEach((control) => { control.disabled = Boolean(savedTag && control.dataset.tag); });
			if (savedTag) tile.querySelector('[data-action="remove"]').textContent = 'Retry removal';
			return;
		}

		const next = tile.nextElementSibling || tile.previousElementSibling;
		const focused = tile.contains(document.activeElement) || document.activeElement === document.body;
		tile.remove();
		const count = tiles.childElementCount;
		const result = savedTag ? `${ztfId} marked ${savedTag.toLowerCase()}.` : `${ztfId} removed.`;
		notificationStatus.textContent = `${result} ${count ? count + ' pending' : 'No pending notifications.'}`;
		if (focused && !document.getElementById('notifications').hidden) {
			const focusTarget = next?.querySelector('[data-tag]:enabled, [data-action="remove"]:enabled')
				|| document.querySelector('#notifications h2');
			focusTarget.focus({preventScroll: true});
		}
	});
})();
