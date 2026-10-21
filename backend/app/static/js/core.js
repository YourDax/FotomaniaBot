/* Общие константы, состояние интерфейса, вспомогательные функции и обращение к API. */

export const $ = (id) => document.getElementById(id);
export const qa = (selector, root) => Array.from((root || document).querySelectorAll(selector));
export const esc = (value) =>
  String(value === null || value === undefined ? '' : value).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]),
  );

export const STATUS_NAMES = {
  DRAFT: 'Черновик',
  RUNNING: 'В работе',
  WAITING_REVIEW: 'Ожидает подтверждения',
  COMPLETED: 'Завершена',
  PAUSED: 'Приостановлена',
  STOPPED: 'Остановлена',
  PENDING: 'Ожидает',
  PROCESSING: 'Обрабатывается',
  REQUIRES_REVIEW: 'Ждёт оператора',
  CONTACT_NOT_FOUND: 'Контакт не найден',
  MAX_ERROR: 'Ошибка MAX',
  SENT: 'Готово',
  FAILED: 'Ошибка',
  UNKNOWN: 'Неизвестно',
  CANCELLED: 'Отменена',
};
export const TASK_STATUSES = [
  'PENDING', 'PROCESSING', 'REQUIRES_REVIEW', 'CONTACT_NOT_FOUND',
  'MAX_ERROR', 'SENT', 'FAILED', 'UNKNOWN', 'CANCELLED',
];
export const DONE_STATUSES = ['SENT', 'FAILED', 'CANCELLED'];
export const BAD_STATUSES = ['FAILED', 'CANCELLED', 'CONTACT_NOT_FOUND', 'MAX_ERROR'];
export const EDITABLE_TASK_STATUSES = ['PENDING', 'REQUIRES_REVIEW', 'CONTACT_NOT_FOUND', 'MAX_ERROR'];

export const statusName = (code) => STATUS_NAMES[code] || code || '—';
export const fmtDateTime = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ru-RU');
};
export const fmtTime = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('ru-RU');
};
export const plural = (n, one, few, many) => {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
};
export const debounce = (fn, ms) => {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
};

export const PREF_KEY = 'fotomania.prefs';

export const S = {
  health: null,
  schools: [],
  contacts: [],
  campaigns: [],
  campaign: null,
  tasks: [],
  templates: { KR: [], RK: [] },
  route: 'home',
  busy: false,
  prefs: { theme: 'light', refreshMs: 5000, pageSize: 50, collapsed: [] },
  collapsed: new Set(),
  contactsUi: { q: '', school: '', klass: '', role: '', optedOut: '', page: 1, selected: new Set() },
  campaignsUi: { q: '', status: '', page: 1, pageSize: 25, selected: new Set() },
  tasksUi: { campaignId: null, q: '', role: '', sort: 'id', page: 1, statusFilter: '', selectedId: null, updatedAt: null, cursor: null, cursorCampaignId: null, campaignSignature: '' },
  recipients: { selected: new Set(), query: '' },
  importUi: { headers: [], rows: [], mapping: {}, showAll: false, step: 1, fileName: '' },
  bulk: { running: false, cancel: false },
  refreshTimer: null,
  messageSets: {},
  maxBusy: false,
};

try {
  Object.assign(S.prefs, JSON.parse(localStorage.getItem(PREF_KEY) || '{}'));
} catch (error) {
  console.warn('Не удалось прочитать настройки интерфейса', error);
}

export const savePrefs = () => {
  localStorage.setItem(PREF_KEY, JSON.stringify(S.prefs));
};

export class UiError extends Error {}

export function explain(status, data) {
  if (data && typeof data.detail === 'string') return data.detail;
  if (data && Array.isArray(data.detail) && data.detail.length) {
    return data.detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : '';
        return `${field ? field + ': ' : ''}${item.msg || 'некорректное значение'}`;
      })
      .join('; ');
  }
  if (status === 403) return 'Действие запрещено настройками доступа.';
  if (status === 404) return 'Объект не найден — возможно, он уже удалён.';
  if (status === 409) return 'Конфликт данных: такая запись уже существует.';
  if (status === 413) return 'Файл слишком большой (лимит 10 МБ).';
  if (status === 422) return 'Проверьте заполнение полей.';
  if (status >= 500) return 'Сервер не смог выполнить операцию. Подробности в журнале backend/logs/session.log.';
  return 'Операция не выполнена.';
}

export async function api(path, options = {}) {
  const opts = { ...options };
  const headers = { ...(opts.headers || {}) };
  if (!(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch('/api' + path, { ...opts, headers });
  } catch (error) {
    throw new UiError('Нет связи с локальным сервером. Проверьте, что приложение запущено.');
  }
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) throw new UiError(explain(response.status, data));
  return data;
}
