import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
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
  const [overflow, setOverflow] = useState({ left: false, right: false });
  const allCategories = Object.keys(CATEGORY_COLORS);

  const updateOverflow = useCallback(() => {
    const bar = barRef.current;
    if (!bar) return;
    const maxScroll = bar.scrollWidth - bar.clientWidth;
    setOverflow({
      left: bar.scrollLeft > 2,
      right: maxScroll > 2 && bar.scrollLeft < maxScroll - 2,
    });
  }, []);

  useEffect(() => {
    const bar = barRef.current;
    if (!bar) return;
    updateOverflow();
    bar.addEventListener('scroll', updateOverflow, { passive: true });
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(updateOverflow);
      observer.observe(bar);
    } else {
      window.addEventListener('resize', updateOverflow);
    }
    return () => {
      bar.removeEventListener('scroll', updateOverflow);
      observer?.disconnect();
      window.removeEventListener('resize', updateOverflow);
    };
  }, [updateOverflow]);

  useEffect(() => {
    const active = barRef.current?.querySelector<HTMLElement>(
      `[data-category="${activeCategory}"]`,
    );
    active?.scrollIntoView({ block: 'nearest', inline: 'center' });
    // Let the scroll settle, then refresh the overflow arrows.
    const timer = window.setTimeout(updateOverflow, 260);
    return () => window.clearTimeout(timer);
  }, [activeCategory, updateOverflow]);

  const scrollByPage = (direction: -1 | 1) => {
    const bar = barRef.current;
    if (!bar) return;
    bar.scrollBy({
      left: direction * Math.max(180, bar.clientWidth * 0.65),
      behavior: 'smooth',
    });
  };

  return (
    <div className="category-filter">
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

      {overflow.left && (
        <button
          type="button"
          className="category-filter__nav category-filter__nav--left"
          onClick={() => scrollByPage(-1)}
          aria-label={t('scroll_categories_left')}
        >
          <ChevronLeft size={14} />
        </button>
      )}
      {overflow.right && (
        <button
          type="button"
          className="category-filter__nav category-filter__nav--right"
          onClick={() => scrollByPage(1)}
          aria-label={t('scroll_categories_right')}
        >
          <ChevronRight size={14} />
        </button>
      )}
    </div>
  );
};
