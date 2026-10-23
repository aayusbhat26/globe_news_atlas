import React, { useEffect, useRef } from 'react';
import { CATEGORY_COLORS } from '../../utils/colors';
import { useTranslation } from 'react-i18next';
import './Controls.css';

interface CategoryFilterProps {
  activeCategory: string;
  onSelectCategory: (category: string) => void;
}

export const CategoryFilter: React.FC<CategoryFilterProps> = ({
  activeCategory,
  onSelectCategory,
}) => {
  const { t } = useTranslation();
  const barRef = useRef<HTMLDivElement>(null);
  const allCategories = Object.keys(CATEGORY_COLORS);

  useEffect(() => {
    const active = barRef.current?.querySelector<HTMLElement>(
      `[data-category="${activeCategory}"]`,
    );
    active?.scrollIntoView({ block: 'nearest', inline: 'center' });
  }, [activeCategory]);

  return (
    <div
      ref={barRef}
      className="category-filter-bar"
      role="toolbar"
      aria-label={t('filter_by_category')}
    >
      <button
        type="button"
        className={`category-chip category-chip--all ${activeCategory === 'all' ? 'category-chip--active' : ''}`}
        onClick={() => onSelectCategory('all')}
        aria-pressed={activeCategory === 'all'}
        data-category="all"
      >
        <span>{t('category.all')}</span>
      </button>

      {allCategories.map((category) => {
        const isActive = activeCategory === category;
        return (
          <button
            key={category}
            type="button"
            className={`category-chip ${isActive ? 'category-chip--active' : ''}`}
            onClick={() => onSelectCategory(category)}
            aria-pressed={isActive}
            data-category={category}
            style={{ '--chip-color': CATEGORY_COLORS[category] } as React.CSSProperties}
          >
            <span className="category-chip__dot" style={{ backgroundColor: CATEGORY_COLORS[category] }} />
            <span>{t(`category.${category}`, category)}</span>
          </button>
        );
      })}
    </div>
  );
};
