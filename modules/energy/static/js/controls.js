// Switching devices from the Control panel: inverter, charger, SUP, alternator, AC limit, operating modes and the Float notice.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function clearActiveMode() {
  ['motor', 'anchor', 'marina', 'sail'].forEach(mode => $('mode-' + mode).classList.remove('active'));
}
function activateMode(mode) {
  clearActiveMode();
  if (mode) $('mode-' + mode).classList.add('active');
}
function toggleInv() {
  clearActiveMode();
  post('/api/control/inverter', { enabled: !(+state.combimaster.inverter_enabled >= 0.5) });
}
function toggleSupport() {
  clearActiveMode();
  post('/api/control/ac-support', { enabled: !(+state.combimaster.ac_support_enabled >= 0.5) });
}
function toggleChg() {
  clearActiveMode();
  post('/api/control/charger', { enabled: !(+state.combimaster.charger_enabled >= 0.5) });
}
async function toggleAlternator() {
  const current = !!state.sources?.alternator?.control_on;
  if (current) {
    const ok = await confirmAlternatorOff();
    if (!ok) return;
  }
  clearActiveMode();
  post('/api/control/alternator', { enabled: !current });
}
function setLimit() {
  const input = $('limit'),
    raw = input.value.trim();
  if (!/^(?:[3-9]|1[0-5])$/.test(raw)) {
    showLimitInvalid();
    return;
  }
  clearActiveMode();
  showErr('');
  post('/api/control/ac-limit', { amps: Number(raw) });
}
// ---- dialogs ----------------------------------------------------------------------------------------------------------------
// Every dialog is a `.backdrop` element that is shown by adding the class `open`.
function setBackdrop(backdrop, open) {
  backdrop.classList.toggle('open', open);
  backdrop.setAttribute('aria-hidden', open ? 'false' : 'true');
}
// A message with a single OK button. Returns the function that closes it (the OK button calls it too).
function showInfoDialog(backdropId, okId, onClose) {
  const backdrop = $(backdropId),
    ok = $(okId);
  const close = () => {
    setBackdrop(backdrop, false);
    ok.removeEventListener('click', close);
    if (onClose) onClose();
  };
  ok.addEventListener('click', close);
  setBackdrop(backdrop, true);
  requestAnimationFrame(() => ok.focus());
  return close;
}
// A safety question with Cancel (the default, focused) and a confirming button. Resolves true only when confirmed;
// Escape, a click on the backdrop and Cancel all answer false.
function confirmDialog(backdropId, cancelId, confirmId) {
  return new Promise(resolve => {
    const backdrop = $(backdropId),
      cancel = $(cancelId),
      confirm = $(confirmId);
    let done = false;
    const finish = answer => {
      if (done) return;
      done = true;
      setBackdrop(backdrop, false);
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onBackdrop);
      cancel.removeEventListener('click', onCancel);
      confirm.removeEventListener('click', onConfirm);
      resolve(answer);
    };
    const onKey = e => {
      if (e.key === 'Escape') {
        e.preventDefault();
        finish(false);
      }
    };
    const onBackdrop = e => {
      if (e.target === backdrop) finish(false);
    };
    const onCancel = () => finish(false),
      onConfirm = () => finish(true);
    setBackdrop(backdrop, true);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onBackdrop);
    cancel.addEventListener('click', onCancel);
    confirm.addEventListener('click', onConfirm);
    requestAnimationFrame(() => cancel.focus());
  });
}
function showLimitInvalid() {
  showInfoDialog('limitInvalid', 'limitInvalidOk', () =>
    requestAnimationFrame(() => {
      const input = $('limit');
      if (input) {
        input.focus();
        input.select();
      }
    })
  );
}
function showFloatInfo() {
  showInfoDialog('floatInfo', 'floatInfoOk');
}
let modeProgressTimer = null;
function showModeProgress(mode) {
  const backdrop = $('modeProgress');
  const label = mode.charAt(0).toUpperCase() + mode.slice(1);
  $('modeProgressText').textContent = 'Setting ' + label + ' mode';
  setBackdrop(backdrop, true);
  if (modeProgressTimer) clearTimeout(modeProgressTimer);
  modeProgressTimer = setTimeout(() => {
    setBackdrop(backdrop, false);
    modeProgressTimer = null;
  }, 6000);
}
function showModeAlreadyActive(mode) {
  const label = mode.charAt(0).toUpperCase() + mode.slice(1);
  $('modeAlreadyText').textContent = label + ' mode already active';
  showInfoDialog('modeAlready', 'modeAlreadyOk');
}
function setMode(mode) {
  if ($('mode-' + mode).classList.contains('active')) {
    showModeAlreadyActive(mode);
    return;
  }
  activateMode(mode);
  showModeProgress(mode);
  post('/api/control/mode', { mode });
}
function confirmEcuOff() {
  return confirmDialog('ecuSafety', 'ecuOffCancel', 'ecuOffConfirm');
}
function confirmAlternatorOff() {
  return confirmDialog('alternatorSafety', 'alternatorOffCancel', 'alternatorOffConfirm');
}
async function toggleDevice(name) {
  const cfg = (state.controls || {})[name];
  if (!cfg || !cfg.verified) {
    return showErr(name + ' control is not mapped/verified yet');
  }
  const current = !!cfg.current;
  if (name === 'engine_ecu' && current) {
    const ok = await confirmEcuOff();
    if (!ok) return;
  }
  clearActiveMode();
  await post('/api/control/device/' + name, { enabled: !current });
}
