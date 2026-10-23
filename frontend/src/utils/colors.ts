export const CATEGORY_COLORS: Record<string, string> = {
  conflict: '#C15B4E',
  politics: '#5C7FA3',
  economy: '#8E8750',
  disaster: '#C98C49',
  protest: '#A86B7D',
  science: '#5E8394',
  health: '#6D8873',
  environment: '#6E8A5F',
  technology: '#7A7990',
  sports: '#B07B52',
  other: '#9A9488',
};

export const CATEGORY_COLORS_LIGHT: Record<string, string> = {
  conflict: '#A32A1F',
  politics: '#1F4E79',
  economy: '#7A6500',
  disaster: '#A85800',
  protest: '#85344A',
  science: '#245D70',
  health: '#2F6141',
  environment: '#3C6427',
  technology: '#4A3F75',
  sports: '#8D4A1E',
  other: '#4F4A42',
};

export const RELATION_COLORS: Record<string, string> = {
  trade: '#6C876B',
  talks: '#5C7896',
  sanctions: '#A64B43',
  military: '#A97843',
  aid: '#8A7D4C',
};

export const SPECTRUM_COLORS = {
  left: '#4F6F99',
  centre: '#8B7A4E',
  right: '#A65353',
  unrated: '#807B70',
};

export const CATEGORY_LABELS: Record<string, string> = {
  conflict: 'Conflict',
  politics: 'Politics',
  economy: 'Economy',
  disaster: 'Disaster',
  protest: 'Protest',
  science: 'Science',
  health: 'Health',
  environment: 'Environment',
  technology: 'Technology',
  sports: 'Sports',
  other: 'Other',
};

export function getCategoryColor(category: string): string {
  const light = typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'light';
  const palette = light ? CATEGORY_COLORS_LIGHT : CATEGORY_COLORS;
  return palette[category.toLowerCase()] || palette.other;
}

export function getRelationColor(relationType: string): string {
  return RELATION_COLORS[relationType.toLowerCase()] || RELATION_COLORS.talks;
}
