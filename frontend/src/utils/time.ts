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

/**
 * A compact age without a trailing preposition, used inside copy that already
 * supplies the wording ("last update {{time}} ago").
 */
export function formatAgeShort(dateString?: string | null): string {
  if (!dateString) return i18n.t('time_unknown');
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return i18n.t('time_unknown');

  const diffMinutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  if (diffMinutes < 1) return 'moments';
  if (diffMinutes < 60) return `${diffMinutes} min`;
  const hours = Math.round(diffMinutes / 60);
  if (hours < 24) return `${hours} hr`;
  return `${Math.round(hours / 24)} d`;
}
