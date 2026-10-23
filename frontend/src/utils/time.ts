import i18n from '../i18n';

export function formatRelativeTime(dateString?: string | null): string {
  if (!dateString) return i18n.t('time_unknown');

  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return i18n.t('time_unknown');

  const diffSec = Math.round((date.getTime() - Date.now()) / 1000);
  const locale = i18n.resolvedLanguage || i18n.language || 'en';

  try {
    const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto', style: 'short' });
    const abs = Math.abs(diffSec);
    if (abs < 60) return formatter.format(0, 'second');
    if (abs < 3600) return formatter.format(Math.round(diffSec / 60), 'minute');
    if (abs < 86400) return formatter.format(Math.round(diffSec / 3600), 'hour');
    if (abs < 86400 * 30) return formatter.format(Math.round(diffSec / 86400), 'day');
    if (abs < 86400 * 365) return formatter.format(Math.round(diffSec / (86400 * 30)), 'month');
    return formatter.format(Math.round(diffSec / (86400 * 365)), 'year');
  } catch {
    const minutes = Math.round(Math.abs(diffSec) / 60);
    if (minutes < 1) return i18n.t('time_unknown');
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.round(minutes / 60);
    return hours < 24 ? `${hours}h` : `${Math.round(hours / 24)}d`;
  }
}
