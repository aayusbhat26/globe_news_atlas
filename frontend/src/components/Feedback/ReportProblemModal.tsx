import React, { useRef, useState } from 'react';
import { X, CheckCircle2 } from 'lucide-react';
import { submitFeedback } from '../../services/api';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useTranslation } from 'react-i18next';
import './ReportProblemModal.css';

interface ReportProblemModalProps {
  eventId: string | null;
  isOpen: boolean;
  onClose: () => void;
}

export const ReportProblemModal: React.FC<ReportProblemModalProps> = ({
  eventId,
  isOpen,
  onClose,
}) => {
  const [category, setCategory] = useState<string>('wrong_location');
  const [details, setDetails] = useState<string>('');
  const [submitted, setSubmitted] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useTranslation();
  const modalRef = useRef<HTMLDivElement>(null);
  useFocusTrap(isOpen, modalRef, onClose);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await submitFeedback({
        event_id: eventId || undefined,
        category,
        details: details.trim(),
      });
      setSubmitted(true);
      setTimeout(() => {
        setSubmitted(false);
        setDetails('');
        onClose();
      }, 1800);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('report_error'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="report-modal-backdrop" onClick={onClose} role="presentation">
      <div
        ref={modalRef}
        className="report-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-modal-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="report-modal__header">
          <h3 className="report-modal__title" id="report-modal-title">
            {t('report_problem')}
          </h3>
          <button type="button" data-autofocus className="report-modal__close" onClick={onClose} aria-label={t('close')}>
            <X size={18} />
          </button>
        </div>

        {submitted ? (
          <div className="report-modal__success" role="status">
            <CheckCircle2 size={36} color="var(--accent-emerald)" />
            <p style={{ fontWeight: 600, marginTop: 8 }}>{t('report_recorded')}</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="report-modal__form">
            <label className="form-label">
              {t('issue_category')}
              <select
                className="form-select"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="wrong_location">{t('issue_wrong_location')}</option>
                <option value="wrong_summary">{t('issue_wrong_summary')}</option>
                <option value="wrong_spectrum">{t('issue_wrong_spectrum')}</option>
                <option value="missing_source">{t('issue_missing_source')}</option>
                <option value="disputed_territory">{t('issue_disputed_territory')}</option>
                <option value="other">{t('issue_other')}</option>
              </select>
            </label>

            <label className="form-label">
              {t('additional_details')}
              <textarea
                className="form-textarea"
                rows={4}
                placeholder={t('report_placeholder')}
                value={details}
                onChange={(e) => setDetails(e.target.value)}
              />
            </label>

            {error && (
              <p className="report-modal__error" role="alert" aria-live="assertive">
                {error}
              </p>
            )}

            <div className="report-modal__actions">
              <button type="button" className="btn-secondary" onClick={onClose} disabled={submitting}>
                {t('cancel')}
              </button>
              <button type="submit" className="btn-primary" disabled={submitting}>
                {submitting ? t('submitting') : t('submit_report')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
