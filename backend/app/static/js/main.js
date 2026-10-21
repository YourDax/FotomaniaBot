/* Школьные рассылки MAX — интерфейс оператора (ES-модули, без сборки).
 *
 * Принципы:
 *  - вся работа с API идёт через api() из core.js;
 *  - разметку рендерят функции render*, никаких inline-обработчиков;
 *  - авто-обновление перерисовывает только изменившиеся задания, чтобы не терять
 *    прокрутку, страницу списка и открытые формы.
 */
import { initMessageSets, loadCampaigns } from './campaigns.js';
import { $, S } from './core.js';
import { applyPrefs } from './dashboard.js';
import { bindCampaignEvents, bindEvents, bindSettingsEvents, bindTaskEvents } from './events.js';
import { checkHealth, go, ROUTES, toggleSidebar } from './router.js';
import { loadSchools } from './schools.js';
import { refreshTasks } from './tasks.js';
import { toast } from './ui.js';

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
