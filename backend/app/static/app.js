/* Школьные рассылки MAX — логика интерфейса оператора.
 *
 * Принципы:
 *  - вся работа с API идёт через api(), логика авторизации сосредоточена там же;
 *  - разметку рендерят функции render*, никаких inline-обработчиков;
 *  - авто-обновление перерисовывает только таблицу заданий, чтобы не терять
 *    прокрутку, страницу списка и открытые формы.
 */
'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const qa = (selector, root) => Array.from((root || document).querySelectorAll(selector));
  const esc = (value) =>
    String(value === null || value === undefined ? '' : value).replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]),
    );

  const STATUS_NAMES = {
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
  const TASK_STATUSES = [
    'PENDING', 'PROCESSING', 'REQUIRES_REVIEW', 'CONTACT_NOT_FOUND',
    'MAX_ERROR', 'SENT', 'FAILED', 'UNKNOWN', 'CANCELLED',
  ];
  const DONE_STATUSES = ['SENT', 'FAILED', 'CANCELLED'];
  const BAD_STATUSES = ['FAILED', 'CANCELLED', 'CONTACT_NOT_FOUND', 'MAX_ERROR'];
  const EDITABLE_TASK_STATUSES = ['PENDING', 'REQUIRES_REVIEW', 'CONTACT_NOT_FOUND', 'MAX_ERROR'];

  const statusName = (code) => STATUS_NAMES[code] || code || '—';
  const statusTone = (code) =>
    DONE_STATUSES.includes(code) && code === 'SENT' ? 'ok'
      : BAD_STATUSES.includes(code) ? 'err'
        : code === 'REQUIRES_REVIEW' || code === 'PENDING' ? 'warn' : '';

  const fmtDateTime = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ru-RU');
  };
  const fmtTime = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('ru-RU');
  };
  const plural = (n, one, few, many) => {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
    return many;
  };
  const debounce = (fn, ms) => {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  };

  const PREF_KEY = 'fotomania.prefs';

  const S = {
    health: null,
    mode: 'manual',
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
    tasksUi: { campaignId: null, q: '', role: '', sort: 'id', page: 1, statusFilter: '', selectedId: null, updatedAt: null },
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

  const savePrefs = () => {
    localStorage.setItem(PREF_KEY, JSON.stringify(S.prefs));
  };

  class UiError extends Error {}

  function explain(status, data) {
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

  async function api(path, options = {}) {
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

  // --- Уведомления и диалоги -------------------------------------------------

  function toast(text, tone = 'ok', details = null) {
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

  function closeModal() {
    const dialog = $('modal');
    if (dialog.open) dialog.close();
    if (dialog.__onCancel) {
      const callback = dialog.__onCancel;
      dialog.__onCancel = null;
      callback();
    }
  }

  function setModalBusy(busy) {
    const confirmButton = $('modalConfirm');
    const cancelButton = $('modalCancel');
    if (confirmButton) confirmButton.setAttribute('aria-busy', busy ? 'true' : 'false');
    if (confirmButton) confirmButton.disabled = busy;
    if (cancelButton) cancelButton.disabled = busy;
  }

  function submitModal() {
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

  function openModal(config) {
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

  const confirmAction = (title, text, options = {}) =>
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

  const promptAction = (title, fields, confirmText = 'Сохранить') =>
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

  // --- Выбор получателей -----------------------------------------------------

  async function selectRecipients() {
    if (!S.schools.length) await loadSchools();
    if (!S.contacts.length) {
      S.contacts = await api('/clients');
      renderContacts();
    }
    const rows = S.contacts.filter((item) => !item.opted_out);
    if (!rows.length) {
      toast('Нет доступных контактов: добавьте их вручную или импортируйте таблицу', 'warn');
      return;
    }
    const schoolName = (id) => (S.schools.find((s) => s.id === id) || {}).name || '';
    const className = (id) => {
      for (const school of S.schools) {
        const found = (school.classes || []).find((item) => item.id === id);
        if (found) return found.name;
      }
      return '';
    };
    const selected = new Set(S.recipients.selected);

    const paint = () => {
      const query = ($('pickSearch').value || '').trim().toLowerCase();
      const visible = rows.filter((item) => {
        if (!query) return true;
        const haystack = `${item.name} ${schoolName(item.school_id)} ${className(item.class_id)} ${item.phone || ''}`.toLowerCase();
        return haystack.includes(query);
      });
      $('pickList').innerHTML = visible.length
        ? visible.map((item) => `
            <label class="item">
              <input type="checkbox" data-pick="${item.id}" ${selected.has(item.id) ? 'checked' : ''}>
              <span>${esc(item.name)}
                <small>${esc(schoolName(item.school_id) || 'без школы')} · ${esc(className(item.class_id) || 'без класса')} · ${item.role === 'KR' ? 'КР' : 'РК'}</small>
              </span>
            </label>`).join('')
        : '<p class="muted" style="padding:10px">Ничего не найдено.</p>';
      qa('[data-pick]', $('pickList')).forEach((input) => {
        input.addEventListener('change', () => {
          const id = Number(input.dataset.pick);
          if (input.checked) selected.add(id);
          else selected.delete(id);
          $('pickCount').textContent = `Выбрано: ${selected.size}`;
        });
      });
      $('pickCount').textContent = `Выбрано: ${selected.size}`;
    };

    openModal({
      title: 'Получатели рассылки',
      body: `
        <div class="search" style="margin-bottom:10px">
          <input id="pickSearch" type="search" placeholder="Поиск по ФИО, школе, классу">
        </div>
        <div class="row" style="margin-bottom:10px">
          <button type="button" class="btn small ghost" id="pickAll">Выбрать всех</button>
          <button type="button" class="btn small ghost" id="pickNone">Снять выбор</button>
          <span class="spacer" style="flex:1"></span>
          <span class="pill" id="pickCount">Выбрано: 0</span>
        </div>
        <div class="picker" id="pickList"></div>`,
      confirmText: 'Применить',
      onSubmit: () => {
        S.recipients.selected = selected;
        renderPicker();
        renderCampaignSelection();
        toast(`Выбрано получателей: ${selected.size}`);
        return true;
      },
    });

    $('pickSearch').addEventListener('input', debounce(paint, 150));
    $('pickAll').addEventListener('click', () => { rows.forEach((item) => selected.add(item.id)); paint(); });
    $('pickNone').addEventListener('click', () => { selected.clear(); paint(); });
    paint();
  }

  // --- Маршрутизация и навигация --------------------------------------------

  const ROUTES = {
    home: { title: 'Обзор', hint: 'Сводка по школам, контактам и рассылкам' },
    schools: { title: 'Школы и классы', hint: 'Структура школ с контактами КР и РК по классам' },
    contacts: { title: 'Контакты КР и РК', hint: 'Единый список с поиском, фильтрами и массовыми действиями' },
    import: { title: 'Импорт таблицы', hint: 'Загрузка XLSX или CSV с автоматическим определением столбцов' },
    campaigns: { title: 'Рассылки', hint: 'Создание рассылок и управление подготовкой сообщений' },
    tasks: { title: 'Задания рассылки', hint: 'Подготовка сообщений в MAX и подтверждение результата' },
    settings: { title: 'Настройки', hint: 'Режим доставки, доступ оператора и внешний вид' },
  };

  function toggleSidebar(open) {
    $('sidebar').classList.toggle('open', open);
    $('scrim').classList.toggle('hidden', !open);
  }

  function go(route, params = {}) {
    const target = ROUTES[route] ? route : 'home';
    S.route = target;
    qa('.view').forEach((view) => view.classList.add('hidden'));
    const section = $('route-' + target);
    if (section) section.classList.remove('hidden');
    qa('.nav button').forEach((button) => {
      const active = button.dataset.route === target
        || (target === 'tasks' && button.dataset.route === 'campaigns');
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    $('viewTitle').textContent = ROUTES[target].title;
    $('viewHint').textContent = ROUTES[target].hint;
    toggleSidebar(false);
    if (location.hash !== '#' + target) history.replaceState(null, '', '#' + target);
    if (target === 'schools') loadSchools().catch((error) => toast(error.message, 'error'));
    if (target === 'contacts') loadContacts().catch((error) => toast(error.message, 'error'));
    if (target === 'campaigns') {
      loadContacts().catch(() => {});
      loadCampaigns().catch((error) => toast(error.message, 'error'));
      loadMessageTemplates().catch(() => {});
    }
    if (target === 'home') refreshDashboard().catch(() => {});
    if (target === 'settings') loadSettings().catch((error) => toast(error.message, 'error'));
    if (target === 'tasks') {
      const campaignId = params.campaignId || S.tasksUi.campaignId;
      openTasks(campaignId).catch((error) => toast(error.message, 'error'));
      startAutoRefresh();
    } else {
      stopAutoRefresh();
    }
  }

  // --- Здоровье, статистика, настройки --------------------------------------

  function renderHealth() {
    const data = S.health;
    const ok = Boolean(data && data.status === 'ok');
    const pill = $('healthPill');
    const sidePill = $('sideHealthPill');
    pill.className = 'pill ' + (ok ? 'ok' : 'err');
    pill.innerHTML = `<span class="dot"></span>${ok ? 'сервер работает' : 'сервер недоступен'}`;
    sidePill.className = 'pill ' + (ok ? 'ok' : 'err');
    sidePill.innerHTML = `<span class="dot"></span>${ok ? 'online' : 'offline'}`;
    $('homeStatusServer').textContent = ok ? 'доступен' : 'нет ответа — проверьте, запущено ли приложение';
    $('homeStatusWorker').textContent = data ? (data.worker ? 'активен' : 'не запущен') : '—';
    $('homeStatusIntegration').textContent = data ? String(data.integration || '—') : '—';
    $('homeStatusMode').textContent = data ? (data.mode === 'manual' ? 'ручной' : String(data.mode || '—')) : '—';
    $('settingsWorker').textContent = data ? (data.worker ? 'активен' : 'не запущен') : '—';
    $('settingsIntegration').textContent = data ? String(data.integration || '—') : '—';
    $('settingsMode').textContent = S.mode === 'manual' ? 'ручной (автоотправка выключена)' : S.mode;
  }

  async function checkHealth(silent = false) {
    try {
      S.health = await api('/health');
    } catch (error) {
      S.health = null;
      if (!silent) toast(error.message, 'error');
    }
    renderHealth();
    return S.health;
  }

  async function loadSettings() {
    const data = await api('/settings');
    S.mode = data.mode || 'manual';
    renderHealth();
  }

  // --- Школы и классы -------------------------------------------------------

  function contactCount(school, role) {
    return (school.classes || [])
      .flatMap((item) => item.contacts || [])
      .filter((contact) => !role || contact.role === role).length;
  }

  function schoolOptions(selectedId, includeAllLabel) {
    const head = includeAllLabel ? `<option value="">${esc(includeAllLabel)}</option>` : '';
    return head + S.schools
      .map((school) => `<option value="${school.id}" ${Number(selectedId) === school.id ? 'selected' : ''}>${esc(school.name)}</option>`)
      .join('');
  }

  function classOptions(schoolId, selectedId) {
    const school = S.schools.find((item) => item.id === Number(schoolId));
    const head = '<option value="">Все классы</option>';
    if (!school) return head;
    return head + (school.classes || [])
      .map((item) => `<option value="${item.id}" ${Number(selectedId) === item.id ? 'selected' : ''}>${esc(item.name)}</option>`)
      .join('');
  }

  function renderSchoolOptions() {
    $('importSchoolSelect').innerHTML = schoolOptions(null, 'Выберите школу');
    $('contactSchool').innerHTML = schoolOptions(S.contactsUi.school, 'Все школы');
    $('contactClass').innerHTML = classOptions(S.contactsUi.school, S.contactsUi.klass);
  }

  function updateNavCounts() {
    const contacts = S.schools.reduce(
      (total, school) => total + (school.classes || []).reduce((sum, item) => sum + (item.contacts || []).length, 0),
      0,
    );
    $('navCountSchools').textContent = S.schools.length;
    $('navCountContacts').textContent = contacts;
    $('navCountCampaigns').textContent = S.campaigns.length;
  }

  async function loadSchools() {
    S.schools = await api('/schools');
    renderSchoolOptions();
    renderSchools();
    renderPicker();
    updateNavCounts();
    return S.schools;
  }

  // --- Сворачивание школ и классов -------------------------------------------
  // Ключи: s<id> — школа, c<id> — класс. Состояние общее для всех разделов,
  // где встречаются школы (список школ, выбор получателей), и хранится в настройках.

  const schoolKey = (id) => `s${id}`;
  const classKey = (id) => `c${id}`;

  function saveCollapsed() {
    S.prefs.collapsed = Array.from(S.collapsed);
    savePrefs();
  }

  function applyCollapsed(block, collapsed) {
    block.classList.toggle('is-collapsed', collapsed);
    const body = block.querySelector('.collapse-body');
    if (body) body.hidden = collapsed;
    qa('[data-action="collapse-toggle"]', block).forEach((node) => {
      node.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });
  }

  function toggleCollapse(element) {
    const block = element.closest('[data-collapse]');
    if (!block) return;
    const key = block.dataset.collapse;
    const collapsed = !S.collapsed.has(key);
    if (collapsed) S.collapsed.add(key);
    else S.collapsed.delete(key);
    applyCollapsed(block, collapsed);
    saveCollapsed();
  }

  function setAllCollapsed(scope, collapsed) {
    const container = scope === 'picker' ? $('campaignPicker') : $('schoolList');
    if (!container) return;
    container.querySelectorAll('[data-collapse]').forEach((block) => {
      const key = block.dataset.collapse;
      if (collapsed) S.collapsed.add(key);
      else S.collapsed.delete(key);
      applyCollapsed(block, collapsed);
    });
    saveCollapsed();
  }

  function renderSchools() {
    const query = ($('schoolSearch').value || '').trim().toLowerCase();
    const list = S.schools.filter((school) => {
      if (!query) return true;
      if (school.name.toLowerCase().includes(query)) return true;
      return (school.classes || []).some((item) => item.name.toLowerCase().includes(query));
    });
    const classes = S.schools.reduce((sum, school) => sum + (school.classes || []).length, 0);
    const contacts = S.schools.reduce(
      (sum, school) => sum + (school.classes || []).reduce((part, item) => part + (item.contacts || []).length, 0),
      0,
    );
    $('schoolsInfo').textContent = S.schools.length
      ? `Школ: ${S.schools.length} · классов: ${classes} · контактов: ${contacts}${query ? ` · найдено школ: ${list.length}` : ''}`
      : 'Пока нет ни одной школы. Добавьте школу и класс или импортируйте таблицу.';

    $('schoolList').innerHTML = list.length
      ? list.map((school) => {
        const key = schoolKey(school.id);
        const collapsed = !query && S.collapsed.has(key);
        return `
        <div class="card school-card collapse-block${collapsed ? ' is-collapsed' : ''}" data-collapse="${key}">
          <div class="card-head collapse-head">
            <button type="button" class="collapse-toggle" data-action="collapse-toggle" data-collapse-key="${key}"
                    aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="schoolBody${school.id}"
                    title="Свернуть или развернуть школу"></button>
            <button type="button" class="school-name" data-action="collapse-toggle" data-collapse-key="${key}"
                    aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="schoolBody${school.id}"
                    title="Свернуть или развернуть школу">${esc(school.name)}</button>
            <span class="badge">${(school.classes || []).length} ${plural((school.classes || []).length, 'класс', 'класса', 'классов')}</span>
            <span class="badge ok">КР: ${contactCount(school, 'KR')}</span>
            <span class="badge">РК: ${contactCount(school, 'RK')}</span>
            <span class="spacer"></span>
            <button type="button" class="btn small ghost" data-action="school-add-class" data-id="${school.id}">Добавить класс</button>
            <button type="button" class="btn small ghost" data-action="school-rename" data-id="${school.id}">Переименовать</button>
            <button type="button" class="btn small danger" data-action="school-delete" data-id="${school.id}">Удалить</button>
          </div>
          <div class="collapse-body" id="schoolBody${school.id}"${collapsed ? ' hidden' : ''}>
            ${schoolClassList(school, Boolean(query))}
          </div>
        </div>`;
      }).join('')
      : `<div class="empty">${query ? 'По запросу ничего не найдено.' : 'Школ пока нет.'}
           <div><button type="button" class="btn primary" data-action="school-create">Добавить школу и класс</button></div>
         </div>`;
  }

  function schoolClassList(school, expandAll) {
    const classes = school.classes || [];
    if (!classes.length) return '<p class="muted">Классов пока нет. Добавьте первый класс.</p>';
    return classes.map((item) => {
      const key = classKey(item.id);
      const collapsed = !expandAll && S.collapsed.has(key);
      return `
      <div class="class-block collapse-block${collapsed ? ' is-collapsed' : ''}" data-collapse="${key}">
        <div class="card-head collapse-head">
          <button type="button" class="collapse-toggle" data-action="collapse-toggle" data-collapse-key="${key}"
                  aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="classBody${item.id}"
                  title="Свернуть или развернуть класс"></button>
          <button type="button" class="class-name" data-action="collapse-toggle" data-collapse-key="${key}"
                  aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="classBody${item.id}"
                  title="Свернуть или развернуть класс">${esc(item.name)}</button>
          <span class="badge mute">${(item.contacts || []).length} ${plural((item.contacts || []).length, 'контакт', 'контакта', 'контактов')}</span>
          <span class="spacer"></span>
          <button type="button" class="btn small ghost" data-action="class-rename" data-id="${item.id}">Переименовать</button>
          <button type="button" class="btn small danger" data-action="class-delete" data-id="${item.id}">Удалить</button>
        </div>
        <div class="collapse-body" id="classBody${item.id}"${collapsed ? ' hidden' : ''}>
          <div class="table-wrap" style="max-height:none">
            <table>
              <thead><tr><th>Роль</th><th>ФИО</th><th>Телефон</th><th>Действия</th></tr></thead>
              <tbody>
                ${(item.contacts || []).length ? (item.contacts || []).map((contact) => `
                  <tr>
                    <td><span class="badge ${contact.role === 'KR' ? 'ok' : 'mute'}">${contact.role === 'KR' ? 'КР' : 'РК'}</span></td>
                    <td>${esc(contact.name)}${contact.opted_out ? ' <span class="badge err">отписался</span>' : ''}</td>
                    <td>${contact.phone ? `<button type="button" class="btn link" data-action="copy" data-copy="${esc(contact.phone)}">${esc(contact.phone)}</button>` : '—'}</td>
                    <td>
                      <button type="button" class="btn small ghost" data-action="contact-edit" data-id="${contact.id}">Изменить</button>
                      <button type="button" class="btn small danger" data-action="contact-delete" data-id="${contact.id}">Удалить</button>
                    </td>
                  </tr>`).join('') : '<tr><td colspan="4" class="empty">Контактов нет</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      </div>`;
    }).join('');
  }

  async function createSchoolAndClass() {
    const values = await promptAction('Новая школа и класс', [
      { id: 'school', label: 'Название школы', required: true, placeholder: 'Например: Школа №12', hint: 'Если школа уже существует, укажите её точное название — будет создан только класс.' },
      { id: 'klass', label: 'Класс', required: true, placeholder: 'Например: 5А' },
    ], 'Создать');
    if (values === null) return;
    await api('/classes', { method: 'POST', body: JSON.stringify({ school_name: values.school, class_name: values.klass }) });
    await loadSchools();
    toast('Школа и класс сохранены');
  }

  async function addClassToSchool(id) {
    const school = S.schools.find((item) => item.id === Number(id));
    if (!school) return;
    const values = await promptAction(`Новый класс — ${school.name}`, [
      { id: 'klass', label: 'Класс', required: true, placeholder: 'Например: 7Б' },
    ], 'Создать класс');
    if (values === null) return;
    await api('/classes', { method: 'POST', body: JSON.stringify({ school_name: school.name, class_name: values.klass }) });
    await loadSchools();
    toast('Класс добавлен');
  }

  async function renameSchool(id) {
    const school = S.schools.find((item) => item.id === Number(id));
    if (!school) return;
    const values = await promptAction('Переименовать школу', [
      { id: 'name', label: 'Новое название', required: true, value: school.name },
    ]);
    if (values === null) return;
    await api(`/schools/${school.id}`, { method: 'PATCH', body: JSON.stringify({ name: values.name }) });
    await loadSchools();
    toast('Школа переименована');
  }

  async function deleteSchool(id) {
    const school = S.schools.find((item) => item.id === Number(id));
    if (!school) return;
    const contacts = (school.classes || []).reduce((sum, item) => sum + (item.contacts || []).length, 0);
    const accepted = await confirmAction(
      'Удалить школу',
      `Школа «${school.name}» будет удалена вместе с ${contacts} ${plural(contacts, 'контактом', 'контактами', 'контактами')} и их заданиями в рассылках. Действие необратимо.`,
      { confirmText: 'Удалить школу' },
    );
    if (!accepted) return;
    await api(`/schools/${school.id}`, { method: 'DELETE' });
    await loadSchools();
    toast('Школа удалена');
  }

  function findClass(classId) {
    for (const school of S.schools) {
      const found = (school.classes || []).find((item) => item.id === Number(classId));
      if (found) return { school, item: found };
    }
    return null;
  }

  async function renameClass(id) {
    const found = findClass(id);
    if (!found) return;
    const values = await promptAction(`Переименовать класс — ${found.school.name}`, [
      { id: 'name', label: 'Новое название класса', required: true, value: found.item.name },
    ]);
    if (values === null) return;
    await api(`/classes/${found.item.id}`, { method: 'PATCH', body: JSON.stringify({ name: values.name }) });
    await loadSchools();
    toast('Класс переименован');
  }

  async function deleteClass(id) {
    const found = findClass(id);
    if (!found) return;
    const count = (found.item.contacts || []).length;
    const accepted = await confirmAction(
      'Удалить класс',
      `Класс «${found.item.name}» (${found.school.name}) и ${count} ${plural(count, 'контакт', 'контакта', 'контактов')} будут удалены вместе с заданиями рассылок.`,
      { confirmText: 'Удалить класс' },
    );
    if (!accepted) return;
    await api(`/classes/${found.item.id}`, { method: 'DELETE' });
    await loadSchools();
    toast('Класс удалён');
  }

  // --- Контакты ---------------------------------------------------------------

  function contactFormFields(contact) {
    return [
      { id: 'name', label: 'ФИО', required: true, value: contact ? contact.name : '', placeholder: 'Иванова Мария Петровна' },
      { id: 'role', label: 'Роль', type: 'select', value: contact ? contact.role : 'KR', options: [{ value: 'KR', label: 'КР — классный руководитель' }, { value: 'RK', label: 'РК — родительский комитет' }] },
      { id: 'phone', label: 'Телефон для поиска в MAX', value: contact ? contact.phone || '' : '', placeholder: '+7 999 123-45-67', hint: 'Телефон обязателен для подготовки сообщения в MAX.' },
      { id: 'school', label: 'Школа', type: 'select', value: contact ? String(contact.school_id || '') : '', options: S.schools.map((school) => ({ value: String(school.id), label: school.name })) },
      { id: 'klass', label: 'Класс', type: 'select', value: contact ? String(contact.class_id || '') : '', options: [] },
      { id: 'username', label: 'Имя пользователя MAX', value: contact ? contact.username || '' : '', placeholder: '@username' },
      { id: 'chat_link', label: 'Ссылка на чат MAX', value: contact ? contact.chat_link || '' : '', placeholder: 'https://max.ru/...' },
      { id: 'consent', label: 'Основание согласия', value: contact ? contact.consent_basis || '' : '', placeholder: 'Например: согласие школы от 01.09.2026' },
    ];
  }

  function fillClassSelect(preserve) {
    const school = S.schools.find((item) => item.id === Number($('field-school').value));
    const classSelect = $('field-klass');
    const wanted = preserve ? classSelect.value : '';
    classSelect.innerHTML = (school ? school.classes || [] : [])
      .map((item) => `<option value="${item.id}">${esc(item.name)}</option>`)
      .join('');
    if (wanted && Array.from(classSelect.options).some((option) => option.value === wanted)) {
      classSelect.value = wanted;
    }
  }

  function contactFieldMarkup(field) {
    const control = field.type === 'select'
      ? `<select id="field-${field.id}">${(field.options || []).map((option) => `<option value="${esc(option.value)}" ${String(option.value) === String(field.value) ? 'selected' : ''}>${esc(option.label)}</option>`).join('')}</select>`
      : `<input id="field-${field.id}" value="${esc(field.value)}" placeholder="${esc(field.placeholder || '')}">`;
    return `
      <div class="field" style="margin-bottom:10px">
        <span>${esc(field.label)}${field.required ? ' <span class="req">*</span>' : ''}</span>
        ${control}
        ${field.hint ? `<small class="muted">${esc(field.hint)}</small>` : ''}
      </div>`;
  }

  function readContactForm(contact) {
    const name = ($('field-name').value || '').trim();
    if (!name) {
      toast('Укажите ФИО', 'warn');
      return null;
    }
    const schoolId = Number($('field-school').value);
    const classId = Number($('field-klass').value);
    if (!schoolId) {
      toast('Выберите школу', 'warn');
      return null;
    }
    if (!classId) {
      toast('В выбранной школе нет классов — сначала создайте класс', 'warn');
      return null;
    }
    const rawPhone = ($('field-phone').value || '').trim();
    if (rawPhone && rawPhone.replace(/\D/g, '').length < 10) {
      toast('Телефон должен содержать не менее 10 цифр', 'warn');
      return null;
    }
    const customRaw = ($('field-custom-json').value || '').trim();
    let custom = {};
    if (customRaw) {
      try {
        custom = JSON.parse(customRaw);
      } catch (error) {
        toast('Дополнительные поля должны быть корректным JSON', 'warn');
        return null;
      }
    }
    return {
      name,
      role: $('field-role').value,
      phone: rawPhone || null,
      school_id: schoolId,
      class_id: classId,
      username: ($('field-username').value || '').trim() || null,
      chat_link: ($('field-chat_link').value || '').trim() || null,
      consent_basis: ($('field-consent').value || '').trim() || null,
      opted_out: Boolean($('field-optout').checked),
      custom_fields: custom,
    };
  }

  async function openContactDialog(contactId) {
    if (!S.schools.length) await loadSchools();
    if (!S.contacts.length) S.contacts = await api('/clients');
    const contact = contactId ? S.contacts.find((item) => item.id === Number(contactId)) : null;
    if (contactId && !contact) {
      toast('Контакт не найден — обновите список', 'error');
      return;
    }
    const fields = contactFormFields(contact);
    const schoolField = fields.find((field) => field.id === 'school');
    if (!contact && !schoolField.value && S.schools.length) schoolField.value = String(S.schools[0].id);
    const customJson = contact && contact.custom_fields && Object.keys(contact.custom_fields).length
      ? JSON.stringify(contact.custom_fields, null, 2)
      : '';
    const body = fields.map(contactFieldMarkup).join('') + `
      <label class="check" style="margin-bottom:10px">
        <input type="checkbox" id="field-optout" ${contact && contact.opted_out ? 'checked' : ''}>
        Контакт отписался — исключать из рассылок
      </label>
      <details>
        <summary class="muted">Дополнительные поля (JSON, необязательно)</summary>
        <textarea id="field-custom-json" placeholder='{"класс_руководитель": "да"}'>${esc(customJson)}</textarea>
      </details>`;
    openModal({
      title: contact ? 'Изменить контакт' : 'Новый контакт',
      body,
      confirmText: contact ? 'Сохранить' : 'Создать',
      onReady: () => {
        fillClassSelect(false);
        $('field-school').addEventListener('change', () => fillClassSelect(false));
      },
      onSubmit: async () => {
        const payload = readContactForm(contact);
        if (!payload) return false;
        if (contact) {
          await api(`/clients/${contact.id}`, { method: 'PATCH', body: JSON.stringify(payload) });
          toast('Контакт обновлён');
        } else {
          await api('/clients', { method: 'POST', body: JSON.stringify(payload) });
          toast('Контакт создан');
        }
        await loadSchools();
        await loadContacts();
        return true;
      },
    });
  }

  async function deleteContactById(id) {
    const contact = S.contacts.find((item) => item.id === Number(id));
    const accepted = await confirmAction(
      'Удалить контакт',
      contact
        ? `Контакт «${contact.name}» и все его задания в рассылках будут удалены.`
        : 'Контакт и все его задания в рассылках будут удалены.',
      { confirmText: 'Удалить' },
    );
    if (!accepted) return;
    await api(`/clients/${id}`, { method: 'DELETE' });
    S.contactsUi.selected.delete(Number(id));
    await loadSchools();
    await loadContacts();
    toast('Контакт удалён');
  }

  async function loadContacts() {
    const ui = S.contactsUi;
    const params = [];
    if (ui.q) params.push(['q', ui.q]);
    if (ui.school) params.push(['school_id', ui.school]);
    if (ui.klass) params.push(['class_id', ui.klass]);
    if (ui.optedOut) params.push(['opted_out', ui.optedOut]);
    const query = params.length ? '?' + params.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&') : '';
    const rows = await api('/clients' + query);
    const existing = new Set(rows.map((item) => item.id));
    Array.from(ui.selected).forEach((id) => { if (!existing.has(id)) ui.selected.delete(id); });
    S.contacts = rows;
    renderContacts();
    updateNavCounts();
    return rows;
  }

  function filteredContacts() {
    const ui = S.contactsUi;
    return S.contacts.filter((contact) => (ui.role ? contact.role === ui.role : true));
  }

  function schoolNameById(id) {
    return (S.schools.find((school) => school.id === id) || {}).name || '—';
  }

  function classNameById(id) {
    for (const school of S.schools) {
      const found = (school.classes || []).find((item) => item.id === id);
      if (found) return found.name;
    }
    return '—';
  }

  function renderContacts() {
    const ui = S.contactsUi;
    const rows = filteredContacts();
    const pageSize = ui.pageSize;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (ui.page > pages) ui.page = pages;
    const start = (ui.page - 1) * pageSize;
    const visible = rows.slice(start, start + pageSize);

    $('contactsInfo').textContent = rows.length
      ? `Найдено контактов: ${rows.length}${ui.role ? ` (фильтр роли: ${ui.role === 'KR' ? 'КР' : 'РК'})` : ''}`
      : 'По текущим фильтрам контактов нет.';

    $('contactRows').innerHTML = visible.length
      ? visible.map((contact) => `
        <tr>
          <td><input type="checkbox" class="contact-check" data-id="${contact.id}" ${ui.selected.has(contact.id) ? 'checked' : ''} aria-label="Выбрать ${esc(contact.name)}"></td>
          <td><b>${esc(contact.name)}</b>${contact.opted_out ? ' <span class="badge err">отписался</span>' : ''}</td>
          <td><span class="badge ${contact.role === 'KR' ? 'ok' : 'mute'}">${contact.role === 'KR' ? 'КР' : 'РК'}</span></td>
          <td>${esc(schoolNameById(contact.school_id))}</td>
          <td>${esc(classNameById(contact.class_id))}</td>
          <td>${contact.phone ? `<button type="button" class="btn link" data-action="copy" data-copy="${esc(contact.phone)}">${esc(contact.phone)}</button>` : '—'}</td>
          <td>${contact.chat_link ? '<span class="badge ok">ссылка</span>' : contact.max_user_id ? '<span class="badge">id</span>' : '<span class="badge warn">нет</span>'}</td>
          <td>
            <button type="button" class="btn small ghost" data-action="contact-edit" data-id="${contact.id}">Изменить</button>
            <button type="button" class="btn small danger" data-action="contact-delete" data-id="${contact.id}">Удалить</button>
          </td>
        </tr>`).join('')
      : '<tr><td colspan="8" class="empty">Контактов нет. Добавьте контакт или импортируйте таблицу.</td></tr>';

    qa('.contact-check', $('contactRows')).forEach((input) => {
      input.addEventListener('change', () => {
        const id = Number(input.dataset.id);
        if (input.checked) ui.selected.add(id);
        else ui.selected.delete(id);
        renderContactSelection();
      });
    });
    renderContactSelection();
    $('contactPageInfo').textContent = rows.length
      ? `Показано ${start + 1}–${Math.min(start + pageSize, rows.length)} из ${rows.length}`
      : '';
    $('contactPrev').disabled = ui.page <= 1;
    $('contactNext').disabled = ui.page >= pages;
  }

  function renderContactSelection() {
    const ui = S.contactsUi;
    const visibleIds = filteredContacts()
      .slice((ui.page - 1) * ui.pageSize, ui.page * ui.pageSize)
      .map((item) => item.id);
    const allChecked = visibleIds.length > 0 && visibleIds.every((id) => ui.selected.has(id));
    const header = $('selectAllContacts');
    header.checked = allChecked;
    header.indeterminate = !allChecked && visibleIds.some((id) => ui.selected.has(id));
    $('contactBulk').hidden = ui.selected.size === 0;
    $('contactSelectedCount').textContent = `Выбрано: ${ui.selected.size}`;
  }

  async function deleteSelectedContacts() {
    const ids = Array.from(S.contactsUi.selected);
    if (!ids.length) return;
    const accepted = await confirmAction(
      'Удалить контакты',
      `Будет удалено ${ids.length} ${plural(ids.length, 'контакт', 'контакта', 'контактов')} вместе с их заданиями в рассылках.`,
      { confirmText: 'Удалить контакты' },
    );
    if (!accepted) return;
    const result = await api('/clients/delete', {
      method: 'POST',
      body: JSON.stringify({ client_ids: ids }),
    });
    S.contactsUi.selected.clear();
    await loadSchools();
    await loadContacts();
    toast(`Удалено контактов: ${result.deleted}`);
  }

  function downloadCsv(filename, header, rows) {
    const safe = (value) => {
      const text = value === null || value === undefined ? '' : String(value);
      const guarded = /^[=+\-@]/.test(text) ? `'${text}` : text;
      return `"${guarded.replace(/"/g, '""')}"`;
    };
    const content = [header, ...rows].map((row) => row.map(safe).join(';')).join('\r\n');
    const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function exportContacts() {
    const ui = S.contactsUi;
    const rows = ui.selected.size
      ? S.contacts.filter((contact) => ui.selected.has(contact.id))
      : filteredContacts();
    if (!rows.length) {
      toast('Нет данных для экспорта', 'warn');
      return;
    }
    downloadCsv(
      `contacts-${new Date().toISOString().slice(0, 10)}.csv`,
      ['ФИО', 'Роль', 'Школа', 'Класс', 'Телефон', 'MAX user id', 'Ссылка', 'Отписался', 'Согласие'],
      rows.map((contact) => [
        contact.name,
        contact.role,
        schoolNameById(contact.school_id),
        classNameById(contact.class_id),
        contact.phone || '',
        contact.max_user_id || '',
        contact.chat_link || '',
        contact.opted_out ? 'да' : 'нет',
        contact.consent_basis || '',
      ]),
    );
    toast(`Экспортировано контактов: ${rows.length}`);
  }

  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement('textarea');
        helper.value = text;
        helper.setAttribute('readonly', 'readonly');
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        document.execCommand('copy');
        helper.remove();
      }
      toast('Скопировано в буфер обмена');
    } catch (error) {
      toast('Не удалось скопировать: ' + error.message, 'error');
    }
  }

  // --- Импорт таблицы ---------------------------------------------------------

  const IMPORT_FIELDS = [
    { value: 'class_name', label: 'Класс', required: true },
    { value: 'kr_name', label: 'ФИО КР', required: true },
    { value: 'kr_phone', label: 'Телефон КР', required: true },
    { value: 'rk_name', label: 'ФИО РК', required: true },
    { value: 'rk_phone', label: 'Телефон РК', required: true },
  ];

  function normalizeHeader(value) {
    return String(value || '')
      .toLowerCase()
      .replace(/ё/g, 'е')
      .replace(/[^а-яa-z0-9]+/g, ' ')
      .trim();
  }

  function detectField(header) {
    // Сравниваем целые слова: иначе «Первоклассник» или «класса» в описании
    // столбца ошибочно считаются колонкой «Класс».
    const words = ` ${normalizeHeader(header)} `;
    const has = (...terms) => terms.some((term) => words.includes(` ${term} `));
    if (has('класс', 'class')) return 'class_name';
    if (has('кр фио', 'фио кр', 'ф и о кр', 'красный руководитель', 'кл рук', 'классный руководитель')) return 'kr_name';
    if (has('кр телефон', 'телефон кр', 'тел кр', 'номер кр', 'кр тел')) return 'kr_phone';
    if (has('рк фио', 'фио рк', 'ф и о рк', 'родительский комитет', 'родитель комитет', 'рк руководитель')) return 'rk_name';
    if (has('рк телефон', 'телефон рк', 'тел рк', 'номер рк', 'рк тел')) return 'rk_phone';
    if (has('фио', 'ф и о', 'name')) return 'kr_name';
    if (has('телефон', 'phone', 'тел')) return 'kr_phone';
    return '';
  }

  // Каждое поле назначается только первому подходящему столбцу файла.
  function detectMapping(headers) {
    const mapping = {};
    const taken = new Set();
    headers.forEach((header) => {
      const field = detectField(header);
      if (field && !taken.has(field)) {
        taken.add(field);
        mapping[header] = field;
      } else {
        mapping[header] = '';
      }
    });
    return mapping;
  }

  function setImportStep(step) {
    S.importUi.step = step;
    qa('#importStepper span').forEach((node) => {
      const value = Number(node.dataset.step);
      node.classList.toggle('active', value === step);
      node.classList.toggle('done', value < step);
    });
  }

  function readImportFile(file) {
    S.importUi.fileName = file ? file.name : '';
    $('importFileName').innerHTML = file
      ? `<b>${esc(file.name)}</b> · ${Math.max(1, Math.round(file.size / 1024))} КБ`
      : 'Файл не выбран. Можно перетащить файл в эту область.';
    $('importPreviewBtn').disabled = !file;
  }

  async function previewImport() {
    const input = $('importFile');
    if (!input.files || !input.files.length) {
      toast('Сначала выберите файл', 'warn');
      return;
    }
    const form = new FormData();
    form.append('file', input.files[0]);
    const data = await api('/imports/preview', { method: 'POST', body: form });
    S.importUi.headers = data.headers || [];
    S.importUi.rows = data.rows || [];
    S.importUi.mapping = detectMapping(S.importUi.headers);
    S.importUi.showAll = false;
    renderImport();
    setImportStep(2);
    $('importStep').classList.remove('hidden');
    $('importResult').innerHTML = '';
    toast(`Файл прочитан: строк ${data.total_rows || S.importUi.rows.length}, найдена строка заголовков №${data.header_row || 1}`);
  }

  function importRowQuality() {
    const ui = S.importUi;
    const classHeader = Object.keys(ui.mapping).find((header) => ui.mapping[header] === 'class_name');
    const nameHeaders = Object.keys(ui.mapping).filter((header) => ['kr_name', 'rk_name'].includes(ui.mapping[header]));
    let withContacts = 0;
    let withoutClass = 0;
    let empty = 0;
    let lastClass = '';
    ui.rows.forEach((row) => {
      const hasContact = nameHeaders.some((header) => String(row[header] || '').trim());
      const classValue = classHeader ? String(row[classHeader] || '').trim() : '';
      if (classValue) lastClass = classValue;
      const hasClass = classValue || lastClass;
      if (!hasContact && !hasClass) empty += 1;
      else if (hasContact && !hasClass) withoutClass += 1;
      else if (hasContact) withContacts += 1;
    });
    return { withContacts, withoutClass, empty, total: ui.rows.length };
  }

  function renderImport() {
    const ui = S.importUi;
    const detected = ui.headers.map((header) => ui.mapping[header] || '');
    const missing = IMPORT_FIELDS.filter((field) => !detected.includes(field.value));
    const duplicates = detected.filter((value, index) => value && detected.indexOf(value) !== index);
    const quality = importRowQuality();

    const notices = [];
    if (!ui.headers.length) {
      notices.push('<div class="notice warn">В файле не найдено ни одного столбца с данными.</div>');
    } else if (missing.length) {
      notices.push(
        `<div class="notice warn">Не определены столбцы: ${missing.map((field) => esc(field.label)).join(', ')}. Укажите их вручную — без них часть контактов не импортируется. ` +
        `Импорт требует как минимум столбец «Класс» и одну пару «ФИО/телефон».</div>`,
      );
    } else {
      notices.push('<div class="notice">Все обязательные столбцы определены. Проверьте сопоставление перед импортом.</div>');
    }
    if (duplicates.length) {
      notices.push(`<div class="notice warn">Один и тот же столбец назначен несколько раз: ${duplicates.map((value) => esc(value)).join(', ')}. Лишние назначения будут проигнорированы.</div>`);
    }
    notices.push(
      `<div class="notice info">Строк в файле: ${quality.total}. Готово к импорту: ${quality.withContacts}` +
      `${quality.withoutClass ? `, без класса: ${quality.withoutClass}` : ''}` +
      `${quality.empty ? `, полностью пустых: ${quality.empty}` : ''}. ` +
      'Повторяющиеся пары «класс + ФИО + роль» сервер пропустит.</div>',
    );
    $('importWarnings').innerHTML = notices.join('');

    $('importMapping').innerHTML = ui.headers.map((header) => `
      <div class="field">
        <span>${esc(header || '(без названия)')}${detected[ui.headers.indexOf(header)] ? ' <span class="badge ok">определено</span>' : ''}</span>
        <select data-header="${esc(header)}">
          <option value="">Не использовать</option>
          ${IMPORT_FIELDS.map((field) => `<option value="${field.value}" ${detected[ui.headers.indexOf(header)] === field.value ? 'selected' : ''}>${esc(field.label)}${field.required ? ' *' : ''}</option>`).join('')}
        </select>
      </div>`).join('');
    qa('#importMapping select').forEach((select) => {
      select.addEventListener('change', () => {
        S.importUi.mapping[select.dataset.header] = select.value;
        renderImport();
      });
    });

    const limit = ui.showAll ? ui.rows.length : Math.min(ui.rows.length, 10);
    $('importRowInfo').textContent = ui.rows.length
      ? `Показано ${limit} из ${ui.rows.length} строк`
      : 'Строк с данными нет';
    $('importShowAll').textContent = ui.showAll ? 'Показать первые 10 строк' : 'Показать все строки';
    $('importShowAll').disabled = ui.rows.length <= 10;
    $('importHead').innerHTML = `<tr>${ui.headers.map((header) => `<th>${esc(header)}</th>`).join('')}</tr>`;
    $('importRows').innerHTML = ui.rows.slice(0, limit).map((row) => `
      <tr>${ui.headers.map((header) => {
        const value = String(row[header] === undefined ? '' : row[header]);
        const field = ui.mapping[header];
        const required = IMPORT_FIELDS.some((item) => item.value === field && item.required);
        return `<td>${value ? esc(value) : (required ? '<span class="badge warn">пусто</span>' : '')}</td>`;
      }).join('')}</tr>`).join('') || '<tr><td class="empty">Нет данных</td></tr>';
  }

  async function runImport() {
    const ui = S.importUi;
    const schoolSelect = $('importSchoolSelect');
    const newSchool = ($('importSchoolNew').value || '').trim();
    const schoolName = newSchool || (schoolSelect.value ? schoolSelect.value : '');
    if (!schoolName) {
      toast('Выберите школу в списке или введите название новой школы', 'warn');
      return;
    }
    const mapped = Object.values(ui.mapping).filter(Boolean);
    if (!mapped.length) {
      toast('Назначьте хотя бы один столбец', 'warn');
      return;
    }
    if (!mapped.includes('class_name') || !mapped.some((value) => ['kr_name', 'rk_name'].includes(value))) {
      toast('Для импорта нужны столбец «Класс» и хотя бы один столбец с ФИО', 'warn');
      return;
    }
    const button = $('importRun');
    button.setAttribute('aria-busy', 'true');
    button.disabled = true;
    try {
      const result = await api('/imports/school-contacts', {
        method: 'POST',
        body: JSON.stringify({
          rows: ui.rows,
          mapping: ui.mapping,
          school_name: schoolName,
          duplicate_mode: 'update',
        }),
      });
      setImportStep(3);
      $('importResult').innerHTML =
        `<div class="notice">Импорт завершён. Добавлено контактов: <b>${result.created}</b>, класс исправлен: <b>${result.updated || 0}</b>, пропущено (уже были): <b>${result.skipped}</b>.</div>`;
      toast(`Импорт завершён: добавлено ${result.created}, исправлено классов ${result.updated || 0}, пропущено ${result.skipped}`);
      await loadSchools();
      await loadContacts().catch(() => {});
    } finally {
      button.removeAttribute('aria-busy');
      button.disabled = false;
    }
  }

  function resetImport() {
    $('importFile').value = '';
    readImportFile(null);
    S.importUi.headers = [];
    S.importUi.rows = [];
    S.importUi.mapping = {};
    S.importUi.showAll = false;
    $('importStep').classList.add('hidden');
    $('importResult').innerHTML = '';
    $('importSchoolNew').value = '';
    setImportStep(1);
  }

  // --- Рассылки: выбор получателей и создание --------------------------------

  function pickerContacts() {
    const query = ($('recipientSearch').value || '').trim().toLowerCase();
    const result = [];
    S.schools.forEach((school) => {
      (school.classes || []).forEach((item) => {
        (item.contacts || []).forEach((contact) => {
          const haystack = `${contact.name} ${school.name} ${item.name} ${contact.phone || ''}`.toLowerCase();
          if (query && !haystack.includes(query)) return;
          result.push({ ...contact, school_id: school.id, class_id: item.id, school: school.name, klass: item.name });
        });
      });
    });
    return result;
  }

  function renderPicker() {
    const rows = pickerContacts();
    if (!S.schools.length) {
      $('campaignPicker').innerHTML = '<p class="muted" style="padding:10px">Школ пока нет. Добавьте школу и контакты на вкладке «Школы и классы» или импортируйте таблицу.</p>';
      return;
    }
    const grouped = new Map();
    rows.forEach((row) => {
      if (!grouped.has(row.school_id)) grouped.set(row.school_id, new Map());
      const classes = grouped.get(row.school_id);
      if (!classes.has(row.class_id)) classes.set(row.class_id, []);
      classes.get(row.class_id).push(row);
    });
    if (!grouped.size) {
      $('campaignPicker').innerHTML = '<p class="muted" style="padding:10px">По запросу получатели не найдены.</p>';
      return;
    }
    const query = ($('recipientSearch').value || '').trim().toLowerCase();
    $('campaignPicker').innerHTML = Array.from(grouped.entries()).map(([schoolId, classes]) => {
      const school = S.schools.find((item) => item.id === schoolId);
      const schoolContactIds = Array.from(classes.values()).flat().map((contact) => contact.id);
      const selectedCount = schoolContactIds.filter((id) => S.recipients.selected.has(id)).length;
      const allSelected = schoolContactIds.length > 0 && selectedCount === schoolContactIds.length;
      const key = schoolKey(schoolId);
      const collapsed = !query && S.collapsed.has(key);
      return `
        <div class="group collapse-block${collapsed ? ' is-collapsed' : ''}" data-collapse="${key}">
          <div class="group-head">
            <button type="button" class="collapse-toggle" data-action="collapse-toggle" data-collapse-key="${key}"
                    aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="pickBody${schoolId}"
                    title="Свернуть или развернуть школу"></button>
            <input type="checkbox" data-pick-school="${schoolId}" ${allSelected ? 'checked' : ''} aria-label="Выбрать школу ${esc(school ? school.name : '')}">
            <button type="button" class="group-name" data-action="collapse-toggle" data-collapse-key="${key}"
                    aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="pickBody${schoolId}"
                    title="Свернуть или развернуть школу">${esc(school ? school.name : 'Школа ' + schoolId)}</button>
            <span class="muted">${schoolContactIds.length} ${plural(schoolContactIds.length, 'получатель', 'получателя', 'получателей')}</span>
            ${selectedCount ? `<span class="badge ok">выбрано: ${selectedCount}</span>` : ''}
          </div>
          <div class="class-list collapse-body" id="pickBody${schoolId}"${collapsed ? ' hidden' : ''}>
            ${Array.from(classes.entries()).map(([classId, contacts]) => `
              <div>
                <div class="muted" style="margin:4px 0">${esc(contacts[0].klass || 'без класса')}</div>
                ${contacts.map((contact) => `
                  <label class="item">
                    <input type="checkbox" data-pick-contact="${contact.id}" ${S.recipients.selected.has(contact.id) ? 'checked' : ''} ${contact.opted_out ? 'disabled' : ''}>
                    <span>${esc(contact.name)} <small>${contact.role === 'KR' ? 'КР' : 'РК'}${contact.phone ? ' · ' + esc(contact.phone) : ''}</small></span>
                    ${contact.opted_out ? '<span class="badge err">отписался</span>' : ''}
                  </label>`).join('')}
              </div>`).join('')}
          </div>
        </div>`;
    }).join('');

    qa('[data-pick-contact]', $('campaignPicker')).forEach((input) => {
      input.addEventListener('change', () => {
        const id = Number(input.dataset.pickContact);
        if (input.checked) S.recipients.selected.add(id);
        else S.recipients.selected.delete(id);
        renderPickerSelection();
      });
    });
    qa('[data-pick-school]', $('campaignPicker')).forEach((input) => {
      input.addEventListener('change', () => {
        const schoolId = Number(input.dataset.pickSchool);
        pickerContacts().forEach((contact) => {
          if (contact.school_id !== schoolId || contact.opted_out) return;
          if (input.checked) S.recipients.selected.add(contact.id);
          else S.recipients.selected.delete(contact.id);
        });
        renderPicker();
      });
    });
    renderPickerSelection();
  }

  function recipientStats() {
    const all = [];
    S.schools.forEach((school) => (school.classes || []).forEach((item) => (item.contacts || [])
      .forEach((contact) => all.push({ ...contact, school_id: school.id }))));
    const chosen = all.filter((contact) => S.recipients.selected.has(contact.id));
    return {
      total: chosen.length,
      kr: chosen.filter((contact) => contact.role === 'KR').length,
      rk: chosen.filter((contact) => contact.role === 'RK').length,
      skipped: all.filter((contact) => contact.opted_out && S.recipients.selected.has(contact.id)).length,
      all,
    };
  }

  function renderPickerSelection() {
    const stats = recipientStats();
    $('campaignSelected').textContent = `Выбрано получателей: ${stats.total}`;
    $('campaignSelectedBreakdown').textContent = stats.total
      ? `КР: ${stats.kr} · РК: ${stats.rk}${stats.skipped ? ` · отписавшихся: ${stats.skipped}` : ''}`
      : 'Отметьте получателей или используйте «Выбрать всех»';
  }

  function renderCampaignSelection() {
    renderPickerSelection();
  }

  function previewCampaign() {
    const stats = recipientStats();
    if (!stats.total) {
      toast('Сначала выберите получателей', 'warn');
      return;
    }
    const kr = S.messageSets.KR.read();
    const rk = S.messageSets.RK.read();
    const problem = kr.error || rk.error;
    if (problem) {
      toast(problem, 'warn');
      return;
    }
    const first = stats.all.find((contact) => S.recipients.selected.has(contact.id));
    const own = first.role === 'RK' ? rk.values : kr.values;
    const templates = own.length ? own : (first.role === 'RK' ? kr.values : rk.values);
    if (!templates.length) {
      toast('Заполните текст для КР или РК', 'warn');
      return;
    }
    const rendered = templates
      .map((template, index) => {
        const text = template.split('{name}').join(first.name);
        return templates.length > 1 ? `— Сообщение ${index + 1} из ${templates.length} —\n${text}` : text;
      })
      .join('\n\n');
    $('campaignPreview').textContent = `Кому: ${first.name} (${ROLE_LABEL[first.role] || first.role})\n\n${rendered}`;
    $('campaignPreviewWrap').classList.remove('hidden');
  }

  // --- Рассылки: список, создание, действия -----------------------------------

  function campaignProgress(campaign) {
    const counts = campaign.status_counts || {};
    const total = campaign.task_count || 0;
    const done = DONE_STATUSES.reduce((sum, code) => sum + (counts[code] || 0), 0);
    const review = (counts.REQUIRES_REVIEW || 0) + (counts.PENDING || 0) + (counts.PROCESSING || 0);
    const percent = total ? Math.round((done / total) * 100) : 0;
    return { total, done, review, percent, counts };
  }

  function campaignProgressCell(campaign) {
    const stats = campaignProgress(campaign);
    const tone = stats.percent === 100 ? 'ok' : stats.counts.FAILED ? 'err' : '';
    return `
      <div class="row" style="gap:8px">
        <div class="grow" style="min-width:110px">
          <div class="progress ${tone}"><span style="width:${stats.percent}%"></span></div>
        </div>
        <span class="muted">${stats.done} / ${stats.total}</span>
      </div>
      <span class="muted">${stats.review ? `Ждут оператора: ${stats.review}` : stats.total ? 'Все задания обработаны' : 'Заданий нет'}</span>`;
  }

  async function loadCampaigns() {
    S.campaigns = await api('/campaigns');
    const available = new Set(S.campaigns.map((item) => item.id));
    Array.from(S.campaignsUi.selected).forEach((id) => {
      if (!available.has(id)) S.campaignsUi.selected.delete(id);
    });
    renderCampaigns();
    renderRecentCampaigns();
    renderDashboard();
    updateNavCounts();
    return S.campaigns;
  }

  function filteredCampaigns() {
    const ui = S.campaignsUi;
    const query = ui.q.trim().toLowerCase();
    return S.campaigns.filter((campaign) => {
      if (ui.status && campaign.status !== ui.status) return false;
      if (query && !campaign.name.toLowerCase().includes(query)) return false;
      return true;
    });
  }

  function renderCampaigns() {
    const ui = S.campaignsUi;
    const rows = filteredCampaigns();
    const pages = Math.max(1, Math.ceil(rows.length / ui.pageSize));
    if (ui.page > pages) ui.page = pages;
    const start = (ui.page - 1) * ui.pageSize;
    const visible = rows.slice(start, start + ui.pageSize);

    $('campaignRows').innerHTML = visible.length
      ? visible.map((campaign) => `
        <tr>
          <td><input type="checkbox" class="campaign-check" data-id="${campaign.id}" ${ui.selected.has(campaign.id) ? 'checked' : ''} aria-label="Выбрать рассылку"></td>
          <td>
            <b>${esc(campaign.name)}</b>
            ${campaign.description ? `<span class="muted">${esc(campaign.description)}</span>` : ''}
            <span class="badge ${campaign.status === 'COMPLETED' ? 'ok' : campaign.status === 'STOPPED' ? 'err' : 'mute'}">${esc(statusName(campaign.status))}</span>
          </td>
          <td>${campaign.school_id ? esc(schoolNameById(campaign.school_id)) : '<span class="muted">все школы</span>'}</td>
          <td>${esc(fmtDateTime(campaign.created_at))}</td>
          <td>${campaignProgressCell(campaign)}</td>
          <td>
            <div class="row" style="gap:6px">
              <button type="button" class="btn small ghost" data-action="campaign-open" data-id="${campaign.id}">Задания</button>
              ${campaign.status === 'DRAFT' ? `<button type="button" class="btn small primary" data-action="campaign-start" data-id="${campaign.id}">Запустить</button>` : ''}
              ${['RUNNING', 'WAITING_REVIEW'].includes(campaign.status) ? `<button type="button" class="btn small ghost" data-action="campaign-stop" data-id="${campaign.id}">Остановить</button>` : ''}
              <button type="button" class="btn small ghost" data-action="campaign-export" data-id="${campaign.id}">CSV</button>
              <button type="button" class="btn small danger" data-action="campaign-delete" data-id="${campaign.id}">Удалить</button>
            </div>
          </td>
        </tr>`).join('')
      : '<tr><td colspan="6" class="empty">Рассылок пока нет. Создайте первую рассылку в форме выше.</td></tr>';

    qa('.campaign-check', $('campaignRows')).forEach((input) => {
      input.addEventListener('change', () => {
        const id = Number(input.dataset.id);
        if (input.checked) ui.selected.add(id);
        else ui.selected.delete(id);
        renderCampaignSelection();
      });
    });

    const visibleIds = visible.map((item) => item.id);
    const allChecked = visibleIds.length > 0 && visibleIds.every((id) => ui.selected.has(id));
    const header = $('selectAllCampaigns');
    header.checked = allChecked;
    header.indeterminate = !allChecked && visibleIds.some((id) => ui.selected.has(id));
    $('campaignBulk').hidden = ui.selected.size === 0;
    $('campaignSelectedCount').textContent = `Выбрано: ${ui.selected.size}`;
    $('campaignPageInfo').textContent = rows.length
      ? `Показано ${start + 1}–${Math.min(start + ui.pageSize, rows.length)} из ${rows.length}`
      : '';
    $('campaignPrev').disabled = ui.page <= 1;
    $('campaignNext').disabled = ui.page >= pages;
  }

  function renderRecentCampaigns() {
    const recent = S.campaigns.slice(0, 5);
    $('recentCampaigns').innerHTML = recent.length
      ? `<div class="table-wrap" style="max-height:none">
           <table>
             <thead><tr><th>Рассылка</th><th>Статус</th><th>Прогресс</th><th></th></tr></thead>
             <tbody>${recent.map((campaign) => `
               <tr>
                 <td><b>${esc(campaign.name)}</b><span class="muted">${esc(fmtDateTime(campaign.created_at))}</span></td>
                 <td><span class="badge ${campaign.status === 'COMPLETED' ? 'ok' : campaign.status === 'STOPPED' ? 'err' : 'mute'}">${esc(statusName(campaign.status))}</span></td>
                 <td>${campaignProgressCell(campaign)}</td>
                 <td><button type="button" class="btn small ghost" data-action="campaign-open" data-id="${campaign.id}">Открыть</button></td>
               </tr>`).join('')}</tbody>
           </table>
         </div>`
      : '<p class="muted">Рассылок пока нет. Создайте первую — она появится здесь и в разделе «Рассылки».</p>';
  }

  async function createCampaign() {
    const name = ($('campaignName').value || '').trim();
    const kr = S.messageSets.KR.read();
    const rk = S.messageSets.RK.read();
    const stats = recipientStats();
    if (!name) {
      toast('Укажите название рассылки', 'warn');
      $('campaignName').focus();
      return;
    }
    if (!stats.total) {
      toast('Выберите хотя бы одного получателя', 'warn');
      return;
    }
    if (kr.error || rk.error) {
      toast(kr.error || rk.error, 'warn');
      return;
    }
    if (!kr.values.length && !rk.values.length) {
      toast('Заполните текст хотя бы для одной роли', 'warn');
      return;
    }
    const button = $('campaignCreateBtn');
    button.setAttribute('aria-busy', 'true');
    button.disabled = true;
    try {
      const schoolIds = new Set(stats.all
        .filter((contact) => S.recipients.selected.has(contact.id))
        .map((contact) => contact.school_id));
      const created = await api('/campaigns', {
        method: 'POST',
        body: JSON.stringify({
          name,
          description: ($('campaignDescription').value || '').trim(),
          message: kr.values[0] || rk.values[0],
          messages_kr: kr.values,
          messages_rk: rk.values,
          client_ids: Array.from(S.recipients.selected),
          school_id: schoolIds.size === 1 ? Array.from(schoolIds)[0] : null,
        }),
      });
      toast(`Рассылка создана. Получателей: ${created.task_count}`);
      await loadMessageTemplates().catch(() => {});
      $('campaignName').value = '';
      $('campaignDescription').value = '';
      S.messageSets.KR.reset();
      S.messageSets.RK.reset();
      $('campaignPreviewWrap').classList.add('hidden');
      S.recipients.selected.clear();
      await loadSchools();
      await loadCampaigns();
      go('tasks', { campaignId: created.id });
    } finally {
      button.removeAttribute('aria-busy');
      button.disabled = false;
    }
  }

  async function startCampaign(id) {
    const campaign = S.campaigns.find((item) => item.id === Number(id));
    const accepted = await confirmAction(
      'Запустить рассылку',
      'Кампания перейдёт в работу: приложение начнёт готовить задания и переведёт их в статус ожидания оператора. Автоматическая отправка не выполняется.',
      { confirmText: 'Запустить', danger: false },
    );
    if (!accepted) return;
    await api(`/campaigns/${id}/start`, { method: 'POST' });
    await loadCampaigns();
    toast(`Рассылка «${campaign ? campaign.name : id}» запущена`);
  }

  async function stopCampaign(id) {
    const values = await promptAction('Остановить рассылку', [
      { id: 'reason', label: 'Причина остановки', value: 'Остановлено оператором', required: true },
    ], 'Остановить');
    if (values === null) return;
    await api(`/campaigns/${id}/stop?reason=${encodeURIComponent(values.reason)}`, { method: 'POST' });
    await loadCampaigns();
    if (S.tasksUi.campaignId === Number(id)) await refreshTasks();
    toast('Рассылка остановлена');
  }

  async function deleteCampaign(id) {
    const campaign = S.campaigns.find((item) => item.id === Number(id));
    const accepted = await confirmAction(
      'Удалить рассылку',
      `Рассылка «${campaign ? campaign.name : id}» и все её задания будут удалены. Действие необратимо.`,
      { confirmText: 'Удалить рассылку' },
    );
    if (!accepted) return;
    await api(`/campaigns/${id}`, { method: 'DELETE' });
    S.campaignsUi.selected.delete(Number(id));
    if (S.tasksUi.campaignId === Number(id)) {
      S.tasksUi.campaignId = null;
      go('campaigns');
    }
    await loadCampaigns();
    toast('Рассылка удалена');
  }

  async function deleteSelectedCampaigns() {
    const ids = Array.from(S.campaignsUi.selected);
    if (!ids.length) return;
    const accepted = await confirmAction(
      'Удалить рассылки',
      `Будет удалено ${ids.length} ${plural(ids.length, 'рассылка', 'рассылки', 'рассылок')} вместе с заданиями.`,
      { confirmText: 'Удалить рассылки' },
    );
    if (!accepted) return;
    const result = await api('/campaigns/delete', { method: 'POST', body: JSON.stringify({ campaign_ids: ids }) });
    S.campaignsUi.selected.clear();
    await loadCampaigns();
    toast(`Удалено рассылок: ${result.deleted}`);
  }

  // --- Сохранённые тексты рассылок (КР и РК раздельно) ---------------------------

  const MAX_MESSAGES = 5;
  const ROLE_LABEL = { KR: 'КР', RK: 'РК' };

  const fetchMessageTemplates = (role) => api(`/message-templates/${role}`);

  async function loadMessageTemplates() {
    const [kr, rk] = await Promise.all([
      fetchMessageTemplates('KR'),
      fetchMessageTemplates('RK'),
    ]);
    S.templates = { KR: kr, RK: rk };
    Object.values(S.messageSets).forEach((set) => set.refreshTemplates());
    return S.templates;
  }

  function templateOptions(role) {
    const items = (S.templates && S.templates[role]) || [];
    return '<option value="">Сохранённые тексты…</option>' + items
      .map((item) => {
        const preview = item.body.replace(/\s+/g, ' ').slice(0, 70);
        return `<option value="${item.id}">${esc(preview)}${item.body.length > 70 ? '…' : ''}</option>`;
      })
      .join('');
  }

  /**
   * Набор из 1–5 полей сообщений для роли. Введённые тексты хранятся в state и не
   * теряются, если уменьшить, а затем снова увеличить количество сообщений.
   */
  function createMessageSet(host, role, initial) {
    const label = ROLE_LABEL[role];
    const start = (Array.isArray(initial) && initial.length ? initial : ['']).slice(0, MAX_MESSAGES);
    const state = {
      count: start.length,
      values: Array.from({ length: MAX_MESSAGES }, (_, index) => start[index] || ''),
    };

    const fieldHtml = (index) => {
      const title = state.count > 1 ? `Сообщение ${index + 1} для ${label}` : `Текст для ${label}`;
      return `
        <div class="field msgset-item">
          <span>${title}</span>
          <textarea data-msg-text="${index}" maxlength="4000" placeholder="Здравствуйте, {name}!">${esc(state.values[index])}</textarea>
          <select data-msg-tpl="${index}" aria-label="Сохранённые тексты для сообщения ${index + 1}">${templateOptions(role)}</select>
          <small class="muted"><span data-msg-counter="${index}">${state.values[index].length}</span> / 4000 символов · доступна подстановка {name}</small>
        </div>`;
    };

    function render() {
      const counts = Array.from({ length: MAX_MESSAGES }, (_, index) => index + 1)
        .map((n) => `<option value="${n}" ${n === state.count ? 'selected' : ''}>${n}</option>`).join('');
      host.innerHTML = `
        <div class="msgset-head">
          <span class="msgset-title">Тексты для ${label}</span>
          <label class="msgset-count">Сообщений
            <select data-msg-count aria-label="Сколько сообщений подготовить для ${label}">${counts}</select>
          </label>
        </div>
        ${Array.from({ length: state.count }, (_, index) => fieldHtml(index)).join('')}`;
    }

    host.addEventListener('input', (event) => {
      const area = event.target.closest('[data-msg-text]');
      if (!area) return;
      const index = Number(area.dataset.msgText);
      state.values[index] = area.value;
      const counter = host.querySelector(`[data-msg-counter="${index}"]`);
      if (counter) counter.textContent = String(area.value.length);
    });
    host.addEventListener('change', (event) => {
      const countSelect = event.target.closest('[data-msg-count]');
      if (countSelect) {
        state.count = Math.min(MAX_MESSAGES, Math.max(1, Number(countSelect.value) || 1));
        render();
        return;
      }
      const tpl = event.target.closest('[data-msg-tpl]');
      if (!tpl) return;
      const index = Number(tpl.dataset.msgTpl);
      const item = ((S.templates && S.templates[role]) || []).find((entry) => entry.id === Number(tpl.value));
      tpl.value = '';
      if (!item) return;
      state.values[index] = item.body;
      const area = host.querySelector(`[data-msg-text="${index}"]`);
      if (area) area.value = item.body;
      const counter = host.querySelector(`[data-msg-counter="${index}"]`);
      if (counter) counter.textContent = String(item.body.length);
    });

    render();
    return {
      /** values — тексты активных полей; пусто, если все поля пусты; error — если заполнены не все. */
      read() {
        const values = state.values.slice(0, state.count).map((value) => value.trim());
        if (values.every((value) => !value)) return { values: [], error: null };
        const missing = values.findIndex((value) => !value);
        if (missing >= 0) {
          return {
            values,
            error: state.count > 1
              ? `Заполните сообщение ${missing + 1} для ${label} или уменьшите количество сообщений`
              : `Заполните текст для ${label}`,
          };
        }
        return { values, error: null };
      },
      reset() {
        state.count = 1;
        state.values = state.values.map(() => '');
        render();
      },
      refreshTemplates() {
        host.querySelectorAll('[data-msg-tpl]').forEach((select) => {
          select.innerHTML = templateOptions(role);
        });
      },
    };
  }

  function initMessageSets() {
    S.messageSets = {
      KR: createMessageSet($('msgsetKR'), 'KR'),
      RK: createMessageSet($('msgsetRK'), 'RK'),
    };
  }

  // --- Редактирование текста уже созданной рассылки ----------------------------

  function openCampaignMessagesDialog() {
    const campaign = S.campaign;
    if (!campaign) return;
    const sets = {};
    openModal({
      title: 'Изменить тексты рассылки',
      body: `
        <p class="muted" style="margin:0 0 12px">Изменения применятся ко всем заданиям, которые ещё не обработаны. Отправленные, неуспешные и отменённые задания не меняются. Персональные правки отдельных получателей будут перезаписаны, а отметки «черновик готов» сохранятся только у неизменённых сообщений.</p>
        <div class="msgset" id="editSetKR" style="margin-bottom:14px"></div>
        <div class="msgset" id="editSetRK"></div>`,
      confirmText: 'Применить ко всем',
      onReady: () => {
        sets.KR = createMessageSet($('editSetKR'), 'KR', campaign.messages_kr);
        sets.RK = createMessageSet($('editSetRK'), 'RK', campaign.messages_rk);
      },
      onSubmit: async () => {
        const kr = sets.KR.read();
        const rk = sets.RK.read();
        if (kr.error || rk.error) {
          toast(kr.error || rk.error, 'warn');
          return false;
        }
        if (!kr.values.length && !rk.values.length) {
          toast('Заполните текст хотя бы для одной роли', 'warn');
          return false;
        }
        const result = await api(`/campaigns/${campaign.id}/messages`, {
          method: 'PATCH',
          body: JSON.stringify({ messages_kr: kr.values, messages_rk: rk.values }),
        });
        await loadMessageTemplates().catch(() => {});
        await refreshTasks();
        toast(`Тексты обновлены. Изменено заданий: ${result.updated}, пропущено обработанных: ${result.skipped}`);
        return true;
      },
    });
  }

  function openTaskMessageDialog(taskId, messageNo = 1) {
    const task = S.tasks.find((item) => item.id === taskId);
    if (!task) return;
    const entry = (task.messages || []).find((item) => item.index === messageNo);
    if (!EDITABLE_TASK_STATUSES.includes(task.status)) {
      toast('Текст можно менять только у необработанных заданий', 'warn');
      return;
    }
    openModal({
      title: `Текст${(task.messages || []).length > 1 ? ` сообщения ${messageNo}` : ''} для ${task.client}`,
      body: `
        <p class="muted" style="margin:0 0 10px">Правка касается только этого получателя. Черновик в MAX придётся подготовить заново.</p>
        <div class="field">
          <span>Текст сообщения <span class="req">*</span></span>
          <textarea id="editTaskMessage" maxlength="4000">${esc(entry ? entry.text : (task.message || ''))}</textarea>
          <small class="muted"><span id="editTaskCounter">${(entry ? entry.text : (task.message || '')).length}</span> / 4000 символов</small>
        </div>`,
      confirmText: 'Сохранить текст',
      onReady: () => {
        $('editTaskMessage').addEventListener('input', () => {
          $('editTaskCounter').textContent = String($('editTaskMessage').value.length);
        });
      },
      onSubmit: async () => {
        const text = ($('editTaskMessage').value || '').trim();
        if (!text) {
          toast('Текст сообщения не может быть пустым', 'warn');
          return false;
        }
        await api(`/tasks/${taskId}/message`, {
          method: 'PATCH',
          body: JSON.stringify({ message: text, index: messageNo }),
        });
        toast('Текст задания обновлён');
        await refreshTasks();
        return true;
      },
    });
  }

  // --- Задания рассылки -------------------------------------------------------

  async function openTasks(campaignId) {
    if (!campaignId) {
      go('campaigns');
      return;
    }
    S.tasksUi.campaignId = Number(campaignId);
    S.tasksUi.page = 1;
    if (!S.schools.length) await loadSchools();
    if (!S.campaigns.length) await loadCampaigns();
    await refreshTasks();
  }

  async function refreshTasks() {
    const campaignId = S.tasksUi.campaignId;
    if (!campaignId) return;
    const campaign = await api(`/campaigns/${campaignId}`);
    const tasks = await api(`/campaigns/${campaignId}/tasks`);
    S.campaign = campaign;
    S.tasks = tasks;
    if (S.tasksUi.selectedId && !tasks.some((task) => task.id === S.tasksUi.selectedId)) {
      S.tasksUi.selectedId = null;
    }
    S.tasksUi.updatedAt = new Date();
    $('taskLastError').textContent = 'ошибок нет';
    renderTasks();
  }

  function taskFiltered() {
    const ui = S.tasksUi;
    const query = ui.q.trim().toLowerCase();
    let rows = S.tasks.filter((task) => {
      if (ui.statusFilter && task.status !== ui.statusFilter) return false;
      if (ui.role && task.recipient_role !== ui.role) return false;
      if (query) {
        const haystack = `${task.client} ${task.phone || ''} ${task.school || ''} ${task.class_name || ''}`.toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
    if (ui.sort === 'status') rows = rows.slice().sort((a, b) => String(a.status).localeCompare(String(b.status)));
    if (ui.sort === 'name') rows = rows.slice().sort((a, b) => String(a.client).localeCompare(String(b.client), 'ru'));
    if (ui.sort === 'school') {
      rows = rows.slice().sort((a, b) => `${a.school}${a.class_name}`.localeCompare(`${b.school}${b.class_name}`, 'ru'));
    }
    return rows;
  }

  function renderTaskHeader() {
    const campaign = S.campaign || {};
    const stats = campaignProgress(campaign);
    $('taskTitle').textContent = campaign.name ? `${campaign.name}` : 'Задания рассылки';
    const badge = $('taskStatusBadge');
    badge.className = 'badge ' + (campaign.status === 'COMPLETED' ? 'ok' : campaign.status === 'STOPPED' ? 'err' : 'mute');
    badge.textContent = statusName(campaign.status);
    const countLabel = (list) => (list && list.length
      ? `${list.length} ${plural(list.length, 'сообщение', 'сообщения', 'сообщений')}`
      : 'нет');
    $('taskMessagesInfo').textContent =
      `КР: ${countLabel(campaign.messages_kr)} · РК: ${countLabel(campaign.messages_rk)}` +
      (campaign.description ? ` · ${campaign.description}` : '');
    renderBulkMessageSelect();
    $('taskUpdatedAt').textContent = S.tasksUi.updatedAt ? fmtTime(S.tasksUi.updatedAt) : '—';
    $('taskExportLink').href = `/api/reports/${S.tasksUi.campaignId}/export`;
    $('taskStopBtn').classList.toggle('hidden', !['RUNNING', 'WAITING_REVIEW'].includes(campaign.status));
    $('taskProgress').querySelector('span').style.width = `${stats.percent}%`;
    $('taskProgress').className = 'progress ' + (stats.percent === 100 ? 'ok' : (stats.counts.FAILED || 0) > 0 ? 'err' : '');
    $('taskProgressText').textContent = `${stats.done} из ${stats.total} подтверждено`;

    const counts = campaign.status_counts || {};
    const total = campaign.task_count || 0;
    const chips = [['', 'Все', total]]
      .concat(TASK_STATUSES
        .filter((code) => counts[code])
        .map((code) => [code, statusName(code), counts[code]]));
    $('taskChips').innerHTML = chips.map(([code, label, count]) => `
      <button type="button" class="chip" data-task-status="${code}" aria-pressed="${S.tasksUi.statusFilter === code}">
        ${esc(label)} <small>${count}</small>
      </button>`).join('');
    qa('[data-task-status]', $('taskChips')).forEach((button) => {
      button.addEventListener('click', () => {
        S.tasksUi.statusFilter = button.dataset.taskStatus;
        S.tasksUi.page = 1;
        renderTasks();
      });
    });
  }

  function draftBadge(task) {
    const messages = task.messages || [];
    const ready = messages.filter((message) => message.prepared_at).length;
    if (!ready) return '';
    if (messages.length < 2) return '<span class="badge ok">черновик готов</span><br>';
    return `<span class="badge ${ready === messages.length ? 'ok' : 'warn'}">черновики: ${ready} из ${messages.length}</span><br>`;
  }

  const maxMessageCount = () => Math.max(1, ...S.tasks.map((task) => (task.messages || []).length));

  function renderBulkMessageSelect() {
    const select = $('taskBulkMessage');
    const total = maxMessageCount();
    const previous = Number(select.value) || 1;
    select.innerHTML = Array.from({ length: total }, (_, index) => `<option value="${index + 1}">№${index + 1}</option>`).join('');
    select.value = String(Math.min(previous, total));
    $('taskBulkMessageWrap').hidden = total < 2;
  }

  const prepareLabel = (total, message) =>
    `Подготовить в MAX${total > 1 ? ` ${message.index}` : ''}${message.prepared_at ? ' ✓' : ''}`;

  function prepareButtons(task, className, only) {
    const total = (task.messages || []).length;
    return (only || task.messages || []).map((message) => `
      <button type="button" class="btn small ${className}" data-action="task-prepare" data-id="${task.id}" data-msg="${message.index}"
        title="${message.prepared_at ? 'Черновик уже подготовлен; повторная подготовка заменит текст в поле ввода' : 'Вставить текст сообщения в поле ввода MAX'}">${prepareLabel(total, message)}</button>`).join('');
  }

  function paintTaskRows() {
    const ui = S.tasksUi;
    const rows = taskFiltered();
    const pageSize = ui.pageSize;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (ui.page > pages) ui.page = pages;
    const start = (ui.page - 1) * pageSize;
    const visible = rows.slice(start, start + pageSize);

    $('taskListInfo').textContent = `Показано ${visible.length} из ${rows.length}`;
    $('taskRows').innerHTML = visible.length
      ? visible.map((task) => `
        <tr data-task-row="${task.id}" class="${ui.selectedId === task.id ? 'selected' : ''}">
          <td>
            <b>${esc(task.client)}</b>
            <span class="muted">${esc(task.phone || 'телефон не указан')}</span>
          </td>
          <td>${esc(task.school || '—')}</td>
          <td>${esc(task.class_name || '—')}</td>
          <td><span class="badge ${task.recipient_role === 'KR' ? 'ok' : 'mute'}">${task.recipient_role === 'KR' ? 'КР' : 'РК'}</span></td>
          <td>
            ${draftBadge(task)}
            ${task.status === 'CONTACT_NOT_FOUND' ? `<span class="badge err">${esc(statusName(task.status))}</span><br>` : ''}
            ${task.opened_at ? '<span class="badge mute">чат открыт</span>' : ''}
            ${task.browser_error ? `<span class="badge err">ошибка MAX</span>` : ''}
          </td>
          <td>
            <select class="task-status-select" data-task-status-select="${task.id}" aria-label="Статус задания">
              ${TASK_STATUSES.map((code) => `<option value="${code}" ${code === task.status ? 'selected' : ''}>${esc(statusName(code))}</option>`).join('')}
            </select>
            ${task.attempts ? `<span class="muted">попыток: ${task.attempts}</span>` : ''}
          </td>
          <td>
            ${task.operator_confirmed_at
              ? `<span class="badge ${task.operator_result === 'sent' ? 'ok' : task.operator_result === 'failed' ? 'err' : 'mute'}">${esc(statusName(task.status))}</span>`
              : '<span class="muted">не подтверждено</span>'}
          </td>
          <td>
            <div class="task-actions">
              ${prepareButtons(task, 'primary')}
              <button type="button" class="btn small ghost" data-action="task-rename" data-id="${task.id}" title="Имя по шаблону, фамилия очищается">Переименовать в MAX</button>
            </div>
          </td>

        </tr>`).join('')
      : '<tr><td colspan="8" class="empty">Заданий по текущему фильтру нет.</td></tr>';

    qa('[data-task-row]', $('taskRows')).forEach((row) => {
      row.addEventListener('click', (event) => {
        if (event.target.closest('select, button, a')) return;
        selectTask(Number(row.dataset.taskRow));
      });
    });
    qa('[data-task-status-select]', $('taskRows')).forEach((select) => {
      select.addEventListener('change', () => {
        updateTaskStatus(Number(select.dataset.taskStatusSelect), select.value).catch((error) => toast(error.message, 'error'));
      });
    });

    $('taskPageInfo').textContent = rows.length
      ? `Показано ${start + 1}–${Math.min(start + pageSize, rows.length)} из ${rows.length}`
      : '';
    $('taskPrev').disabled = ui.page <= 1;
    $('taskNext').disabled = ui.page >= pages;
  }

  function renderTasks() {
    renderTaskHeader();
    paintTaskRows();
    renderTaskDetail();
  }

  function currentTask() {
    return S.tasks.find((task) => task.id === S.tasksUi.selectedId) || null;
  }

  function messageBlocksHtml(task) {
    const messages = task.messages || [];
    if (!messages.length) {
      return `<h3>Текст сообщения</h3>
        <pre class="message">Текст не сформирован: в рассылке нет шаблона для этой роли.</pre>`;
    }
    const editable = EDITABLE_TASK_STATUSES.includes(task.status);
    const hint = messages.length > 1
      ? `<p class="muted" style="margin:0 0 10px">Каждая подготовка заменяет текст в поле ввода чата MAX. Сначала отправьте предыдущее сообщение вручную, затем готовьте следующее.</p>`
      : '';
    return hint + messages.map((message) => `
      <div class="msg-block">
        <div class="card-head">
          <h3>${messages.length > 1 ? `Сообщение ${message.index} из ${messages.length}` : 'Текст сообщения'}</h3>
          ${message.prepared_at ? '<span class="badge ok">черновик готов</span>' : ''}
        </div>
        <div class="task-actions" style="margin-bottom:8px">
          ${prepareButtons(task, 'primary', [message])}
          <button type="button" class="btn small ghost" data-action="task-copy" data-id="${task.id}" data-msg="${message.index}">Копировать текст</button>
          ${editable ? `<button type="button" class="btn small ghost" data-action="task-edit-message" data-id="${task.id}" data-msg="${message.index}">Изменить текст</button>` : ''}
        </div>
        <pre class="message">${esc(message.text)}</pre>
      </div>`).join('');
  }

  function renderTaskDetail() {
    const task = currentTask();
    const box = $('taskDetail');
    if (!task) {
      box.innerHTML = `
        <h3>Карточка задания</h3>
        <p class="muted">Выберите получателя в таблице, чтобы увидеть готовый текст, идентификаторы MAX и историю действий.</p>`;
      $('taskSelectedInfo').hidden = true;
      return;
    }
    $('taskSelectedInfo').hidden = false;
    $('taskSelectedInfo').textContent = `${task.client} · ${statusName(task.status)}`;
    box.innerHTML = `
      <div class="card-head">
        <h3>${esc(task.client)}</h3>
        <span class="badge ${task.recipient_role === 'KR' ? 'ok' : 'mute'}">${task.recipient_role === 'KR' ? 'КР' : 'РК'}</span>
        <span class="spacer"></span>
        <span class="badge ${task.status === 'SENT' ? 'ok' : BAD_STATUSES.includes(task.status) ? 'err' : 'warn'}">${esc(statusName(task.status))}</span>
      </div>
      <div class="row" style="margin-bottom:10px">
        <button type="button" class="btn small ghost" data-action="task-open" data-id="${task.id}">Открыть чат</button>
        <button type="button" class="btn small ghost" data-action="task-rename" data-id="${task.id}" title="Имя по шаблону, фамилия очищается">Переименовать в MAX</button>
      </div>
      ${messageBlocksHtml(task)}
      <h3 style="margin-top:14px">Данные получателя</h3>
      <dl class="kv">
        <dt>Школа</dt><dd>${esc(task.school || '—')}</dd>
        <dt>Класс</dt><dd>${esc(task.class_name || '—')}</dd>
        <dt>Телефон</dt><dd>${esc(task.phone || 'не указан')}</dd>
        <dt>MAX user id</dt><dd>${esc(task.max_user_id || '—')}</dd>
        <dt>Имя пользователя</dt><dd>${esc(task.username || '—')}</dd>
        <dt>Ссылка на чат</dt><dd>${task.chat_link ? `<a href="${esc(task.chat_link)}" target="_blank" rel="noopener">открыть</a>` : '—'}</dd>
        <dt>Попыток</dt><dd>${task.attempts || 0}</dd>
      </dl>
      <h3 style="margin-top:14px">История</h3>
      <dl class="kv">
        <dt>Создано</dt><dd>${esc(fmtDateTime(task.created_at))}</dd>
        <dt>Чат открыт</dt><dd>${esc(fmtDateTime(task.opened_at))}</dd>
        <dt>Черновик готов</dt><dd>${esc(fmtDateTime(task.browser_prepared_at))}</dd>
        <dt>Подтверждено</dt><dd>${esc(fmtDateTime(task.operator_confirmed_at))}</dd>
        <dt>Результат</dt><dd>${esc(task.operator_result || '—')}</dd>
      </dl>
      ${task.error ? `<div class="notice warn" style="margin-top:10px">${esc(task.error)}</div>` : ''}
      ${task.browser_error ? `<div class="notice error" style="margin-top:10px">${esc(task.browser_error)}</div>` : ''}
      <div class="row" style="margin-top:12px">
        <select id="detail-result">
          <option value="sent">Отправлено</option>
          <option value="failed">Не отправлено</option>
          <option value="unknown">Неизвестно</option>
        </select>
        <button type="button" class="btn primary" data-action="task-confirm" data-id="${task.id}">Сохранить результат</button>
      </div>
      <div class="field" style="margin-top:10px">
        <span>Примечание к результату (необязательно)</span>
        <textarea id="detail-note" maxlength="500" placeholder="Например: отправлено вручную, ответа нет">${esc(task.error || '')}</textarea>
      </div>`;
  }

  function selectTask(id) {
    S.tasksUi.selectedId = id;
    paintTaskRows();
    renderTaskDetail();
  }

  async function updateTaskStatus(taskId, status) {
    await api(`/tasks/${taskId}/status`, { method: 'PATCH', body: JSON.stringify({ status }) });
    toast('Статус задания обновлён');
    await refreshTasks();
  }

  // Одновременно в MAX выполняется одна операция (то же ограничение есть на сервере).
  async function withMaxLock(action) {
    if (S.maxBusy) {
      toast('В MAX уже выполняется операция. Дождитесь её завершения.', 'warn');
      return;
    }
    S.maxBusy = true;
    try {
      await action();
    } finally {
      S.maxBusy = false;
    }
  }

  async function prepareTask(taskId, messageNo = 1) {
    await withMaxLock(async () => {
      const buttons = qa('[data-action="task-prepare"]')
        .filter((node) => Number(node.dataset.id) === taskId && Number(node.dataset.msg || 1) === messageNo);
      buttons.forEach((node) => {
        node.setAttribute('aria-busy', 'true');
        node.disabled = true;
      });
      try {
        const result = await api(`/tasks/${taskId}/prepare-max?message_no=${messageNo}`, { method: 'POST' });
        const task = S.tasks.find((item) => item.id === taskId);
        const multi = task && (task.messages || []).length > 1;
        toast(multi
          ? `Сообщение ${messageNo} подготовлено для ${result.client}. Оно заменило текст в поле ввода; отправка не выполнялась.`
          : `Текст подготовлен для ${result.client}. Отправка не выполнялась.`);
        $('taskLastError').textContent = 'последняя подготовка: успех';
      } catch (error) {
        $('taskLastError').textContent = error.message;
        toast(error.message, 'error');
      } finally {
        buttons.forEach((node) => {
          node.removeAttribute('aria-busy');
          node.disabled = false;
        });
        await refreshTasks();
      }
    });
  }

  async function openTaskChat(taskId) {
    await withMaxLock(async () => {
      try {
        const result = await api(`/tasks/${taskId}/open-max`, { method: 'POST' });
        toast(`Чат открыт для ${result.client}. Текст не вставлялся.`);
        // Поиск выполняется во вкладке MAX в подключённом браузере; новую вкладку не открываем.
        $('taskLastError').textContent = 'последнее открытие чата: успех';
      } catch (error) {
        $('taskLastError').textContent = error.message;
        toast(error.message, 'error');
      } finally {
        await refreshTasks();
      }
    });
  }

  async function renameTaskContact(taskId) {
    await withMaxLock(async () => {
      const button = qa('[data-action="task-rename"]').find((node) => Number(node.dataset.id) === taskId);
      if (button) {
        button.setAttribute('aria-busy', 'true');
        button.disabled = true;
      }
      try {
        const result = await api(`/tasks/${taskId}/rename-max`, { method: 'POST' });
        if (result.status === 'ALREADY_CORRECT') {
          toast('Имя контакта в MAX уже корректно, изменений не потребовалось. Страница обновлена.');
        } else {
          toast('Контакт переименован в MAX по шаблону. Фамилия очищена.');
        }
        $('taskLastError').textContent = 'последнее переименование: успех';
      } catch (error) {
        $('taskLastError').textContent = error.message;
        toast(error.message, 'error');
      } finally {
        if (button) {
          button.removeAttribute('aria-busy');
          button.disabled = false;
        }
        await refreshTasks();
      }
    });
  }

  async function confirmTaskResult(taskId) {
    const selected = $('detail-result');
    const note = ($('detail-note').value || '').trim();
    if (!selected) {
      toast('Не найден выбор результата', 'error');
      return;
    }
    await api(`/tasks/${taskId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ result: selected.value, note: note || null }),
    });
    toast('Результат сохранён');
    await refreshTasks();
  }

  async function prepareAll() {
    if (S.bulk.running) {
      toast('Массовая подготовка уже выполняется', 'warn');
      return;
    }
    if (S.maxBusy) {
      toast('В MAX уже выполняется операция. Дождитесь её завершения.', 'warn');
      return;
    }
    const messageNo = Number($('taskBulkMessage').value) || 1;
    const tasks = S.tasks.filter((task) =>
      !DONE_STATUSES.includes(task.status) && (task.messages || []).length >= messageNo);
    if (!tasks.length) {
      toast(`Нет заданий, требующих подготовки сообщения ${messageNo}`, 'warn');
      return;
    }
    const multi = maxMessageCount() > 1;
    const confirmed = await confirmAction(
      'Массовая подготовка черновиков',
      `Будут последовательно обработаны ${tasks.length} ${plural(tasks.length, 'получатель', 'получателя', 'получателей')}` +
      `${multi ? ` (сообщение №${messageNo})` : ''}. ` +
      'Приложение откроет чаты в MAX и вставит текст — отправка НЕ выполняется. ' +
      `${multi ? 'Текст заменит содержимое поля ввода в каждом чате, поэтому предыдущие сообщения нужно отправить заранее. ' : ''}` +
      'Можно остановить процесс в любой момент.',
      { confirmText: 'Начать подготовку', danger: false },
    );
    if (!confirmed) return;
    S.bulk.running = true;
    S.bulk.cancel = false;
    S.maxBusy = true;
    stopAutoRefresh();
    const progressButton = $('taskBulkPrepare');
    progressButton.setAttribute('aria-busy', 'true');
    progressButton.disabled = true;
    const errors = [];
    let prepared = 0;
    let cancelled = false;
    try {
      for (let index = 0; index < tasks.length; index += 1) {
        if (S.bulk.cancel) {
          cancelled = true;
          break;
        }
        const task = tasks[index];
        $('taskLastError').textContent = `Подготовка ${index + 1} из ${tasks.length}: ${task.client}`;
        try {
          await api(`/tasks/${task.id}/prepare-max?message_no=${messageNo}`, { method: 'POST' });
          prepared += 1;
        } catch (error) {
          errors.push(`${task.client}: ${error.message}`);
        }
      }
    } finally {
      S.bulk.running = false;
      S.maxBusy = false;
      progressButton.removeAttribute('aria-busy');
      progressButton.disabled = false;
      await refreshTasks();
      startAutoRefresh();
    }
    const summary = cancelled
      ? `Подготовка остановлена: готово ${prepared} из ${tasks.length}.`
      : `Готово: черновики созданы для ${prepared} из ${tasks.length}. Отправка не выполнялась.`;
    toast(summary, errors.length ? 'warn' : 'ok', errors);
    $('taskLastError').textContent = errors.length ? `Ошибок: ${errors.length}` : 'ошибок нет';
  }

  async function openAllChats() {
    const tasks = S.tasks.filter((task) => !DONE_STATUSES.includes(task.status));
    if (!tasks.length) {
      toast('Нет заданий для открытия чатов', 'warn');
      return;
    }
    const confirmed = await confirmAction(
      'Открыть чаты по списку',
      `Приложение откроет ${tasks.length} ${plural(tasks.length, 'чат', 'чата', 'чатов')} в MAX и отметит факт открытия. ` +
      'Тексты сообщений не вставляются. Продолжить?',
      { confirmText: 'Открыть чаты', danger: false },
    );
    if (!confirmed) return;
    if (S.maxBusy) {
      toast('В MAX уже выполняется операция. Дождитесь её завершения.', 'warn');
      return;
    }
    S.bulk.running = true;
    S.maxBusy = true;
    stopAutoRefresh();
    const errors = [];
    let opened = 0;
    try {
      for (const task of tasks) {
        if (S.bulk.cancel) break;
        $('taskLastError').textContent = `Открытие чата: ${task.client}`;
        try {
          await api(`/tasks/${task.id}/open-max`, { method: 'POST' });
          opened += 1;
        } catch (error) {
          errors.push(`${task.client}: ${error.message}`);
        }
      }
    } finally {
      S.bulk.running = false;
      S.maxBusy = false;
      await refreshTasks();
      startAutoRefresh();
    }
    toast(`Открыто чатов: ${opened} из ${tasks.length}.`, errors.length ? 'warn' : 'ok', errors);
  }

  // --- Автообновление ---------------------------------------------------------

  function autoRefreshEnabled() {
    return $('autoRefreshToggle').checked && S.prefs.refreshMs > 0;
  }

  function stopAutoRefresh() {
    clearInterval(S.refreshTimer);
    S.refreshTimer = null;
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    if (!autoRefreshEnabled() || !S.tasksUi.campaignId) return;
    S.refreshTimer = setInterval(() => {
      if (S.route !== 'tasks' || S.bulk.running) return;
      if (document.hidden) return;
      if (document.activeElement && $('taskRows').contains(document.activeElement)) return;
      refreshTasks().catch((error) => {
        $('taskLastError').textContent = error.message;
      });
    }, S.prefs.refreshMs);
  }

  // --- Обзор ------------------------------------------------------------------

  function renderDashboard() {
    const classes = S.schools.reduce((sum, school) => sum + (school.classes || []).length, 0);
    let kr = 0;
    let rk = 0;
    S.schools.forEach((school) => (school.classes || []).forEach((item) => (item.contacts || [])
      .forEach((contact) => { if (contact.role === 'KR') kr += 1; else rk += 1; })));
    $('kpiSchools').textContent = S.schools.length;
    $('kpiClassesHint').textContent = `классов: ${classes}`;
    $('kpiKr').textContent = kr;
    $('kpiRk').textContent = rk;
    $('kpiCampaigns').textContent = S.campaigns.length;

    let inWork = 0;
    let review = 0;
    S.campaigns.forEach((campaign) => {
      if (['RUNNING', 'WAITING_REVIEW'].includes(campaign.status)) inWork += 1;
      const counts = campaign.status_counts || {};
      review += (counts.REQUIRES_REVIEW || 0) + (counts.PENDING || 0) + (counts.PROCESSING || 0);
    });
    $('kpiCampaignsHint').textContent = `в работе: ${inWork}`;
    $('kpiReview').textContent = review;
  }

  async function refreshDashboard() {
    await Promise.all([loadSchools(), loadCampaigns(), checkHealth(true)]);
  }

  // --- Настройки интерфейса ---------------------------------------------------

  function applyTheme(theme) {
    S.prefs.theme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = S.prefs.theme;
    $('themeSelect').value = S.prefs.theme;
    savePrefs();
  }

  function applyPrefs() {
    applyTheme(S.prefs.theme);
    S.collapsed = new Set(Array.isArray(S.prefs.collapsed) ? S.prefs.collapsed : []);
    $('refreshInterval').value = String(S.prefs.refreshMs);
    $('pageSizeDefault').value = String(S.prefs.pageSize);
    S.contactsUi.pageSize = S.prefs.pageSize;
    $('contactPageSize').value = String(S.prefs.pageSize);
    $('taskPageSize').value = String(Math.min(S.prefs.pageSize, 100));
    S.tasksUi.pageSize = Number($('taskPageSize').value);
  }

  // --- Делегирование действий -------------------------------------------------

  const ACTIONS = {
    'school-create': () => createSchoolAndClass(),
    'school-add-class': (id) => addClassToSchool(id),
    'school-rename': (id) => renameSchool(id),
    'school-delete': (id) => deleteSchool(id),
    'class-rename': (id) => renameClass(id),
    'class-delete': (id) => deleteClass(id),
    'collapse-toggle': (id, element) => toggleCollapse(element),
    'collapse-all': (id, element) => setAllCollapsed(element.dataset.scope, true),
    'collapse-none': (id, element) => setAllCollapsed(element.dataset.scope, false),
    'contact-edit': (id) => openContactDialog(id),
    'contact-delete': (id) => deleteContactById(id),
    'contact-create': () => openContactDialog(null),
    'copy': (id, element) => copyToClipboard(element.dataset.copy || ''),
    'campaign-open': (id) => go('tasks', { campaignId: id }),
    'campaign-start': (id) => startCampaign(id),
    'campaign-stop': (id) => stopCampaign(id),
    'campaign-delete': (id) => deleteCampaign(id),
    'campaign-export': (id) => window.open(`/api/reports/${id}/export`, '_blank', 'noopener'),
    'task-prepare': (id, node) => prepareTask(id, Number(node.dataset.msg) || 1),
    'task-open': (id) => openTaskChat(id),
    'task-rename': (id) => renameTaskContact(id),
    'task-copy': (id, node) => {
      const task = S.tasks.find((item) => item.id === id) || {};
      const entry = (task.messages || []).find((item) => item.index === (Number(node.dataset.msg) || 1));
      return copyToClipboard(entry ? entry.text : (task.message || ''));
    },
    'task-confirm': (id) => confirmTaskResult(id),
    'task-edit-message': (id, node) => openTaskMessageDialog(id, Number(node.dataset.msg) || 1),
    'check-health': () => checkHealth(),
    'refresh-campaigns': () => loadCampaigns().then(() => toast('Список рассылок обновлён')),
  };

  document.addEventListener('click', (event) => {
    const routeTarget = event.target.closest('[data-route]');
    if (routeTarget) {
      go(routeTarget.dataset.route);
      return;
    }
    const actionTarget = event.target.closest('[data-action]');
    if (!actionTarget) return;
    const handler = ACTIONS[actionTarget.dataset.action];
    if (!handler) return;
    event.preventDefault();
    Promise.resolve(handler(Number(actionTarget.dataset.id), actionTarget))
      .catch((error) => toast(error.message, 'error'));
  });

  // --- Привязка обработчиков ---------------------------------------------------

  function bindEvents() {
    qa('.nav button').forEach((button) => {
      button.addEventListener('click', () => go(button.dataset.route));
    });
    $('menuBtn').addEventListener('click', () => toggleSidebar(true));
    $('scrim').addEventListener('click', () => toggleSidebar(false));
    $('themeBtn').addEventListener('click', () => applyTheme(S.prefs.theme === 'dark' ? 'light' : 'dark'));

    $('schoolSearch').addEventListener('input', debounce(renderSchools, 150));
    $('schoolsRefresh').addEventListener('click', () => loadSchools().then(() => toast('Данные школ обновлены')).catch((error) => toast(error.message, 'error')));
    $('btnAddSchool').addEventListener('click', () => ACTIONS['school-create']());

    $('contactsRefresh').addEventListener('click', () => loadContacts().then(() => toast('Список контактов обновлён')).catch((error) => toast(error.message, 'error')));
    $('btnAddContact').addEventListener('click', () => openContactDialog(null));
    $('contactSearch').addEventListener('input', debounce(() => {
      S.contactsUi.q = $('contactSearch').value.trim();
      S.contactsUi.page = 1;
      loadContacts().catch((error) => toast(error.message, 'error'));
    }, 250));
    $('contactSchool').addEventListener('change', () => {
      S.contactsUi.school = $('contactSchool').value;
      S.contactsUi.klass = '';
      S.contactsUi.page = 1;
      $('contactClass').innerHTML = classOptions(S.contactsUi.school, '');
      loadContacts().catch((error) => toast(error.message, 'error'));
    });
    $('contactClass').addEventListener('change', () => {
      S.contactsUi.klass = $('contactClass').value;
      S.contactsUi.page = 1;
      loadContacts().catch((error) => toast(error.message, 'error'));
    });
    $('contactRole').addEventListener('change', () => {
      S.contactsUi.role = $('contactRole').value;
      S.contactsUi.page = 1;
      renderContacts();
    });
    $('contactOptOut').addEventListener('change', () => {
      S.contactsUi.optedOut = $('contactOptOut').value;
      S.contactsUi.page = 1;
      loadContacts().catch((error) => toast(error.message, 'error'));
    });
    $('contactReset').addEventListener('click', () => {
      Object.assign(S.contactsUi, { q: '', school: '', klass: '', role: '', optedOut: '', page: 1 });
      $('contactSearch').value = '';
      $('contactRole').value = '';
      $('contactOptOut').value = '';
      renderSchoolOptions();
      loadContacts().catch((error) => toast(error.message, 'error'));
    });
    $('contactPageSize').addEventListener('change', () => {
      S.contactsUi.pageSize = Number($('contactPageSize').value);
      S.contactsUi.page = 1;
      renderContacts();
    });
    $('contactPrev').addEventListener('click', () => { S.contactsUi.page -= 1; renderContacts(); });
    $('contactNext').addEventListener('click', () => { S.contactsUi.page += 1; renderContacts(); });
    $('selectAllContacts').addEventListener('change', () => {
      const ui = S.contactsUi;
      const pageIds = filteredContacts()
        .slice((ui.page - 1) * ui.pageSize, ui.page * ui.pageSize)
        .map((item) => item.id);
      if ($('selectAllContacts').checked) pageIds.forEach((id) => ui.selected.add(id));
      else pageIds.forEach((id) => ui.selected.delete(id));
      renderContacts();
    });
    $('btnBulkDeleteContacts').addEventListener('click', () => deleteSelectedContacts().catch((error) => toast(error.message, 'error')));
    $('btnClearContactSelection').addEventListener('click', () => {
      S.contactsUi.selected.clear();
      renderContacts();
    });
    $('btnExportContacts').addEventListener('click', () => exportContacts());

    $('importFile').addEventListener('change', () => readImportFile($('importFile').files[0] || null));
    $('importPreviewBtn').addEventListener('click', () => previewImport().catch((error) => toast(error.message, 'error')));
    $('importRun').addEventListener('click', () => runImport().catch((error) => toast(error.message, 'error')));
    $('importReset').addEventListener('click', resetImport);
    $('importShowAll').addEventListener('click', () => {
      S.importUi.showAll = !S.importUi.showAll;
      renderImport();
    });
    const drop = $('importDrop');
    ['dragenter', 'dragover'].forEach((type) => drop.addEventListener(type, (event) => {
      event.preventDefault();
      drop.classList.add('drag');
    }));
    ['dragleave', 'drop'].forEach((type) => drop.addEventListener(type, (event) => {
      event.preventDefault();
      drop.classList.remove('drag');
    }));
    drop.addEventListener('drop', (event) => {
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (!file) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      $('importFile').files = transfer.files;
      readImportFile(file);
    });
  }

  function bindCampaignEvents() {
    $('recipientSearch').addEventListener('input', debounce(renderPicker, 150));
    $('btnSelectAllRecipients').addEventListener('click', () => {
      pickerContacts().forEach((contact) => {
        if (!contact.opted_out) S.recipients.selected.add(contact.id);
      });
      renderPicker();
      toast(`Выбрано получателей: ${S.recipients.selected.size}`);
    });
    $('btnClearRecipients').addEventListener('click', () => {
      S.recipients.selected.clear();
      renderPicker();
    });
    $('campaignPreviewBtn').addEventListener('click', previewCampaign);
    $('campaignCreateBtn').addEventListener('click', () => createCampaign().catch((error) => toast(error.message, 'error')));
    $('campaignSearch').addEventListener('input', debounce(() => {
      S.campaignsUi.q = $('campaignSearch').value.trim();
      S.campaignsUi.page = 1;
      renderCampaigns();
    }, 200));
    $('campaignStatusFilter').addEventListener('change', () => {
      S.campaignsUi.status = $('campaignStatusFilter').value;
      S.campaignsUi.page = 1;
      renderCampaigns();
    });
    $('campaignsRefresh').addEventListener('click', () => loadCampaigns().then(() => toast('Список рассылок обновлён')).catch((error) => toast(error.message, 'error')));
    $('campaignPrev').addEventListener('click', () => { S.campaignsUi.page -= 1; renderCampaigns(); });
    $('campaignNext').addEventListener('click', () => { S.campaignsUi.page += 1; renderCampaigns(); });
    $('selectAllCampaigns').addEventListener('change', () => {
      const ui = S.campaignsUi;
      const pageIds = filteredCampaigns()
        .slice((ui.page - 1) * ui.pageSize, ui.page * ui.pageSize)
        .map((item) => item.id);
      if ($('selectAllCampaigns').checked) pageIds.forEach((id) => ui.selected.add(id));
      else pageIds.forEach((id) => ui.selected.delete(id));
      renderCampaigns();
    });
    $('btnBulkDeleteCampaigns').addEventListener('click', () => deleteSelectedCampaigns().catch((error) => toast(error.message, 'error')));
    $('btnClearCampaignSelection').addEventListener('click', () => {
      S.campaignsUi.selected.clear();
      renderCampaigns();
    });
  }

  function bindTaskEvents() {
    $('taskBack').addEventListener('click', () => go('campaigns'));
    $('taskRefreshBtn').addEventListener('click', () => refreshTasks().then(() => toast('Статусы обновлены')).catch((error) => toast(error.message, 'error')));
    $('taskStopBtn').addEventListener('click', () => stopCampaign(S.tasksUi.campaignId).catch((error) => toast(error.message, 'error')));
    $('taskEditMessagesBtn').addEventListener('click', () => openCampaignMessagesDialog());
    $('taskSearch').addEventListener('input', debounce(() => {
      S.tasksUi.q = $('taskSearch').value.trim();
      S.tasksUi.page = 1;
      paintTaskRows();
    }, 200));
    $('taskRoleFilter').addEventListener('change', () => {
      S.tasksUi.role = $('taskRoleFilter').value;
      S.tasksUi.page = 1;
      paintTaskRows();
    });
    $('taskSort').addEventListener('change', () => {
      S.tasksUi.sort = $('taskSort').value;
      paintTaskRows();
    });
    $('taskPageSize').addEventListener('change', () => {
      S.tasksUi.pageSize = Number($('taskPageSize').value);
      S.tasksUi.page = 1;
      paintTaskRows();
    });
    $('taskPrev').addEventListener('click', () => { S.tasksUi.page -= 1; paintTaskRows(); });
    $('taskNext').addEventListener('click', () => { S.tasksUi.page += 1; paintTaskRows(); });
    $('taskBulkPrepare').addEventListener('click', () => prepareAll().catch((error) => toast(error.message, 'error')));
    $('taskBulkOpen').addEventListener('click', () => openAllChats().catch((error) => toast(error.message, 'error')));
    $('autoRefreshToggle').addEventListener('change', () => {
      if ($('autoRefreshToggle').checked) startAutoRefresh();
      else stopAutoRefresh();
    });
  }

  function bindSettingsEvents() {
    $('themeSelect').addEventListener('change', () => applyTheme($('themeSelect').value));
    $('refreshInterval').addEventListener('change', () => {
      S.prefs.refreshMs = Number($('refreshInterval').value);
      savePrefs();
      startAutoRefresh();
      toast(S.prefs.refreshMs ? `Автообновление: каждые ${S.prefs.refreshMs / 1000} с` : 'Автообновление отключено');
    });
    $('pageSizeDefault').addEventListener('change', () => {
      S.prefs.pageSize = Number($('pageSizeDefault').value);
      savePrefs();
      applyPrefs();
      renderContacts();
      toast(`Строк на странице: ${S.prefs.pageSize}`);
    });
    $('settingsCheckHealth').addEventListener('click', () => checkHealth().then(() => toast('Сервер проверен')));
    $('settingsSync').addEventListener('click', async () => {
      await api('/settings', { method: 'PATCH', body: JSON.stringify({ mode: 'manual' }) });
      await loadSettings();
      toast('Режим доставки синхронизирован: ручной');
    });
  }

  // --- Инициализация ----------------------------------------------------------

  function boot() {
    applyPrefs();
    initMessageSets();
    bindEvents();
    bindCampaignEvents();
    bindTaskEvents();
    bindSettingsEvents();

    window.addEventListener('hashchange', () => {
      const route = location.hash.replace('#', '') || 'home';
      if (route !== S.route) go(route);
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && S.route === 'tasks') refreshTasks().catch(() => {});
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') toggleSidebar(false);
      const tag = document.activeElement ? document.activeElement.tagName : '';
      if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) {
        event.preventDefault();
        if (S.route === 'contacts') $('contactSearch').focus();
        if (S.route === 'campaigns') $('campaignSearch').focus();
        if (S.route === 'tasks') $('taskSearch').focus();
        if (S.route === 'schools') $('schoolSearch').focus();
      }
    });

    const initial = location.hash.replace('#', '');
    Promise.all([loadSchools(), loadCampaigns(), checkHealth(true)])
      .then(() => go(ROUTES[initial] && initial !== 'tasks' ? initial : 'home'))
      .catch((error) => toast(error.message, 'error'));

    setInterval(() => {
      if (!document.hidden) checkHealth(true);
    }, 60000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
