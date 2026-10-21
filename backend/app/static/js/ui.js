/* Уведомления и модальные диалоги. */
import { $, esc } from './core.js';

// --- Уведомления и диалоги -------------------------------------------------

export function toast(text, tone = 'ok', details = null) {
  const box = $('toasts');
  if (!box) return;
  const node = document.createElement('div');
  node.className = `toast ${tone}`;
  const list = Array.isArray(details) && details.length
    ? `<ul>${details.slice(0, 6).map((item) => `<li>${esc(item)}</li>`).join('')}</ul>`
    : '';
  node.innerHTML = `
    <div class="toast-text">${esc(text)}${list}</div>
    <button type="button" aria-label="Закрыть уведомление">✕</button>`;
  node.querySelector('button').addEventListener('click', () => node.remove());
  box.appendChild(node);
  setTimeout(() => node.remove(), tone === 'error' ? 9000 : 5000);
}

export function closeModal() {
  const dialog = $('modal');
  if (dialog.open) dialog.close();
  if (dialog.__onCancel) {
    const callback = dialog.__onCancel;
    dialog.__onCancel = null;
    callback();
  }
}

export function setModalBusy(busy) {
  const confirmButton = $('modalConfirm');
  const cancelButton = $('modalCancel');
  if (confirmButton) confirmButton.setAttribute('aria-busy', busy ? 'true' : 'false');
  if (confirmButton) confirmButton.disabled = busy;
  if (cancelButton) cancelButton.disabled = busy;
}

export function submitModal() {
  const form = $('modalForm');
  if (form && typeof form.__onSubmit === 'function') {
    let result;
    try {
      result = form.__onSubmit(form);
    } catch (error) {
      toast(error.message, 'error');
      return;
    }
    if (result === false) return;
    if (result && typeof result.then === 'function') {
      setModalBusy(true);
      result
        .then((accepted) => {
          setModalBusy(false);
          if (accepted !== false) closeModal();
        })
        .catch((error) => {
          setModalBusy(false);
          toast(error.message, 'error');
        });
      return;
    }
  }
  closeModal();
}

export function openModal(config) {
  const dialog = $('modal');
  const body = $('modalBody');
  const foot = $('modalFoot');
  $('modalTitle').textContent = config.title || 'Диалог';
  body.innerHTML = `<form id="modalForm" novalidate>${config.body || ''}</form>`;
  const form = $('modalForm');
  form.__onSubmit = config.onSubmit || null;
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submitModal();
  });
  foot.innerHTML =
    `<button type="button" class="btn ghost" id="modalCancel">${esc(config.cancelText || 'Отмена')}</button>` +
    `<button type="button" class="btn ${config.danger ? 'danger' : 'primary'}" id="modalConfirm">${esc(config.confirmText || 'Сохранить')}</button>`;
  $('modalCancel').addEventListener('click', closeModal);
  $('modalConfirm').addEventListener('click', submitModal);
  dialog.__onCancel = config.onCancel || null;
  dialog.showModal();
  if (typeof config.onReady === 'function') config.onReady();
  const first = form.querySelector('input, select, textarea');
  if (first) setTimeout(() => first.focus(), 30);
  return dialog;
}

export const confirmAction = (title, text, options = {}) =>
  new Promise((resolve) => {
    openModal({
      title,
      body: `<p class="muted" style="margin:0">${esc(text)}</p>`,
      confirmText: options.confirmText || 'Подтвердить',
      cancelText: options.cancelText || 'Отмена',
      danger: options.danger !== false,
      onSubmit: () => { resolve(true); return true; },
      onCancel: () => resolve(false),
    });
  });

export const promptAction = (title, fields, confirmText = 'Сохранить') =>
  new Promise((resolve) => {
    const control = (field) => {
      if (field.type === 'select') {
        return `<select id="${field.id}">${(field.options || [])
          .map((option) => `<option value="${esc(option.value)}" ${option.value === field.value ? 'selected' : ''}>${esc(option.label)}</option>`)
          .join('')}</select>`;
      }
      if (field.type === 'textarea') {
        return `<textarea id="${field.id}" placeholder="${esc(field.placeholder || '')}">${esc(field.value || '')}</textarea>`;
      }
      return `<input id="${field.id}" type="${field.type || 'text'}" value="${esc(field.value || '')}" placeholder="${esc(field.placeholder || '')}">`;
    };
    const body = fields.map((field) => `
      <div class="field" style="margin-bottom:10px">
        <span>${esc(field.label)}${field.required ? ' <span class="req">*</span>' : ''}</span>
        ${control(field)}
        ${field.hint ? `<small class="muted">${esc(field.hint)}</small>` : ''}
      </div>`).join('');
    openModal({
      title,
      body,
      confirmText,
      onSubmit: () => {
        const values = {};
        for (const field of fields) {
          const raw = ($(field.id).value || '').trim();
          if (field.required && !raw) {
            toast(`Заполните поле «${field.label}»`, 'warn');
            return false;
          }
          values[field.id] = raw;
        }
        resolve(values);
        return true;
      },
      onCancel: () => resolve(null),
    });
  });
