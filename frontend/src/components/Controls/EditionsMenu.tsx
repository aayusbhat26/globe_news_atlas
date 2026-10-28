import React, { useEffect, useRef, useState } from 'react';
import { Bookmark, FileSearch, History, Layers, MessagesSquare, Waypoints } from 'lucide-react';
import { navigate } from '../../router';

const ITEMS = [
  {
    path: '/watchline',
    label: 'My Watchline',
    detail: 'Your places and storylines, with what changed',
    icon: Bookmark,
  },
  {
    path: '/storylines',
    label: 'Storylines',
    detail: 'Relations between countries, followed over time',
    icon: Waypoints,
  },
  {
    path: '/thin-file',
    label: 'The Thin File',
    detail: 'What rests on a single report or a rewritten summary',
    icon: FileSearch,
  },
  {
    path: '/rewind',
    label: 'Atlas Rewind',
    detail: 'Play back the last days of coverage',
    icon: History,
  },
  {
    path: '/x-desk',
    label: 'X Desk',
    detail: 'Live newsroom timelines through X’s official embed',
    icon: MessagesSquare,
  },
];

export const EditionsMenu: React.FC = () => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const go = (path: string) => {
    setOpen(false);
    navigate(path);
  };

  return (
    <div className="editions-menu">
      <button
        ref={triggerRef}
        type="button"
        className={`control-btn editions-trigger${open ? ' is-open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="editions-menu"
        onClick={() => setOpen((current) => !current)}
        title="Editions and lenses"
      >
        <Layers size={15} aria-hidden="true" />
        <span className="editions-trigger__label">Editions</span>
      </button>

      {open && (
        <div className="editions-popover" id="editions-menu" role="menu" ref={menuRef}>
          <span className="editions-popover__kicker">Editions &amp; lenses</span>
          {ITEMS.map(({ path, label, detail, icon: Icon }) => (
            <button
              key={path}
              type="button"
              role="menuitem"
              className="editions-item"
              onClick={() => go(path)}
            >
              <Icon size={16} aria-hidden="true" />
              <span>
                <strong>{label}</strong>
                <small>{detail}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
