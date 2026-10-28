import React, { useEffect } from 'react';
import { ArrowLeft } from 'lucide-react';
import { AuthMasthead } from './AuthLayout';
import { navigate } from '../../router';
import './Account.css';

const TERMS = [
  {
    title: 'The service',
    body: 'Globe News Atlas is an independent public-interest news atlas. It groups reporting from third-party outlets, generates summaries, and links to original sources. The Atlas is not a newsroom, does not endorse the views in cited coverage, and is not a substitute for professional, legal, financial or emergency advice.',
  },
  {
    title: 'Reader accounts',
    body: 'Provide an email address you control, keep your credentials private, and use one account per person. You are responsible for activity under your account. Tell the operator immediately if you believe someone else has access. Accounts are intended for people aged 16 or older.',
  },
  {
    title: 'Acceptable use',
    body: 'Do not attempt to break, overload or probe the authentication system, access another reader’s account, automate account creation, or use the service to harass people or distribute unlawful material. Access to public event data is welcome; please respect reasonable rate limits and the terms of the underlying publishers.',
  },
  {
    title: 'Third-party reporting',
    body: 'Headlines, excerpts and links belong to their publishers. The Atlas stores metadata and short derived summaries. Copyright in the original reporting remains with the publisher. Removing or altering attribution is not permitted.',
  },
  {
    title: 'Availability and changes',
    body: 'The Atlas is provided as-is, without a guarantee of uptime, completeness or accuracy. Features, sources and these terms may change. Material changes to account terms will be surfaced in the product before they take effect.',
  },
  {
    title: 'Closing an account',
    body: 'You can close your account from Account → Close account. The operator may suspend accounts that abuse the service or create a security risk. Closing an account does not remove third-party reporting from the public record.',
  },
];

const PRIVACY = [
  {
    title: 'What the account stores',
    body: 'Your email address, an optional display name, an Argon2id password hash, a Google subject identifier if you connect Google, session records (device string, IP address, timestamps), a short security activity log, the pinned place and storyline keys of any watchline plus its last-visit time, and — if you enable two-factor — an encrypted authenticator secret, its last-used time, and hashed recovery codes. We never store your plaintext password or authenticator secret in readable form. Account data lives in the deployment’s local SQLite database or, when the operator enables it, a managed MySQL/TiDB database over TLS; it is never uploaded to Hugging Face.',
  },
  {
    title: 'Why it is stored',
    body: 'To authenticate you, keep your account secure, show active sessions, send confirmation and reset messages, and let you recover access. Session and activity records exist specifically so you can notice unfamiliar access and sign it out.',
  },
  {
    title: 'Cookies and local storage',
    body: 'The session cookie is HttpOnly and holds an opaque token; the server stores only its hash. A signed CSRF cookie protects state-changing requests. A short-lived OAuth cookie binds Google sign-in to your browser. Theme, language and interface state are kept in local storage. There are no advertising or cross-site tracking cookies on the Atlas, account, event or edition pages. The optional X desk loads X’s official embed only after you choose to load it, and X’s own cookies and privacy policy apply there.',
  },
  {
    title: 'The optional X desk',
    body: 'The X desk is a separate page. It loads X’s official embedded timelines for a curated set of newsroom accounts only after you choose to load them. When loaded, X may set cookies and collect data under X’s privacy policy; this is the only place in the Atlas that loads a third-party social widget. The map, dossiers, account area and editions do not load X widgets. X posts are displayed by X and are not stored or ingested into the Atlas event pipeline.',
  },
  {
    title: 'Email and Google',
    body: 'Transactional email is sent through the operator’s configured provider (for example Resend or an SMTP server) and necessarily includes your address. If Google sign-in is enabled, Google authenticates you and returns a verified email and subject identifier; Google’s own privacy terms apply to that exchange. If breached-password checking is enabled, the server sends the first five characters of a SHA-1 password hash to the Have I Been Pwned k-anonymity API; the password itself is never sent.',
  },
  {
    title: 'Retention and deletion',
    body: 'Account records remain until you close the account. Expired sessions and one-time links are pruned automatically. Closing the account removes the user record, sessions, tokens, linked identities and recovery codes, and anonymises the security log. Backup copies may persist briefly in routine infrastructure backups. Public news records do not contain reader account data.',
  },
  {
    title: 'Your choices',
    body: 'You can update your display name, confirm your email, change your password, manage sessions, enable or disable two-factor, disconnect Google (after setting a password) and close the account. Email changes and passkey management are not part of this release. For access or deletion questions, contact the operator of this deployment or use the project issue tracker.',
  },
  {
    title: 'Security and children',
    body: 'Passwords are hashed with Argon2id, session tokens are hashed at rest, mutating requests require a signed CSRF token, and authentication endpoints are rate limited. No system is perfectly secure. Accounts are not directed to children under 16 and should not be created by them.',
  },
];

export const LegalPage: React.FC<{ kind: 'terms' | 'privacy' }> = ({ kind }) => {
  const isTerms = kind === 'terms';
  const sections = isTerms ? TERMS : PRIVACY;
  const title = isTerms ? 'Terms of use' : 'Privacy Notice';
  const deck = isTerms
    ? 'The ground rules for reading, citing and using the Atlas.'
    : 'What a reader account stores, why it is stored, and what you can do about it.';

  useEffect(() => {
    document.title = `${title} — Globe News Atlas`;
  }, [title]);

  return (
    <div className="legal-shell">
      <AuthMasthead />
      <main className="legal-main">
        <button
          type="button"
          className="auth-back-link"
          onClick={() => {
            if (window.history.length > 1) {
              window.history.back();
            } else {
              navigate('/');
            }
          }}
        >
          <ArrowLeft size={14} aria-hidden="true" />
          Go back
        </button>
        <p className="auth-kicker">Reader accounts · October 2026</p>
        <h1 className="legal-title">{title}</h1>
        <p className="legal-deck">{deck}</p>
        <div className="legal-rule" />
        <ol className="legal-sections">
          {sections.map((section, index) => (
            <li key={section.title}>
              <span className="legal-index" aria-hidden="true">
                {String(index + 1).padStart(2, '0')}
              </span>
              <div>
                <h2>{section.title}</h2>
                <p>{section.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="legal-foot">
          <p>
            {isTerms ? (
              <>
                Read the{' '}
                <a href="/privacy" onClick={(event) => { event.preventDefault(); navigate('/privacy'); }}>
                  Privacy Notice
                </a>{' '}
                alongside these terms.
              </>
            ) : (
              <>
                Read the{' '}
                <a href="/terms" onClick={(event) => { event.preventDefault(); navigate('/terms'); }}>
                  Terms of use
                </a>{' '}
                alongside this notice.
              </>
            )}
          </p>
          <button type="button" className="account-quiet-button" onClick={() => navigate('/')}>
            Return to the atlas
          </button>
        </div>
      </main>
    </div>
  );
};
