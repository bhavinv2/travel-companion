import { useEffect, useRef, useState } from 'react';
import Icon from './Icon.jsx';
import { ArrowButton, Reveal, cx } from './ui.jsx';
import { scrollToId } from '../hooks.js';
import { focusFirstError } from '../validate.js';

/**
 * Card that shows one step at a time with a progress stepper.
 * `steps` is an array of { short, label, content }. `jump` ({ step, nonce }) lets a parent
 * send the user to a given step, e.g. after picking a role elsewhere on the page.
 *
 * `validate(step)` is asked before moving on and before sending; it returns true when the step is
 * fine, and otherwise marks its own fields (the parent owns the errors, because it owns the fields)
 * -- the form then stays put and puts the cursor in the first box that needs fixing. A step can
 * only be reached by passing the ones before it, so the stepper is not a way round it.
 */
export default function MultiStepForm({ anchor, steps, submitLabel, fine, done: doneView, onSubmit, jump, validate }) {
  const [step, setStep] = useState(0);
  const box = useRef(null);
  const ok = (s) => {
    if (!validate || validate(s)) return true;
    // after React has drawn the messages
    setTimeout(() => focusFirstError(box.current?.querySelector('.fstep.show')), 30);
    return false;
  };
  const [done, setDone] = useState(false);
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState('');
  const n = steps.length;
  const last = step === n - 1;

  useEffect(() => {
    if (!jump) return;
    setStep(jump.step);
    setDone(false);
    setFailed('');
  }, [jump]);

  const go = (s) => {
    setStep(s);
    scrollToId(anchor);
  };

  return (
    <Reveal className="fcard">
      <div className="form-live" hidden={done} ref={box}>
        <div className="fhead">
          <span>Step <b><span>{step + 1}</span></b> of {n}</span>
          <span><span>{steps[step].label}</span></span>
        </div>
        <div className="stepper" aria-hidden="true">
          {steps.map((s, i) => (
            <div key={s.short} className={cx('st', i < step && 'done', i === step && 'cur')}>
              <i></i>{s.short}
            </div>
          ))}
        </div>

        {steps.map((s, i) => (
          <div key={s.short} className={cx('fstep', i === step && 'show')}>
            {s.content}
          </div>
        ))}

        <div className="fnav">
          <button type="button" className="ghost" disabled={step === 0} onClick={() => step > 0 && go(step - 1)}>
            <Icon name="arrowLeft" sw={2} />Back
          </button>
          {last ? (
            <ArrowButton
              disabled={sending}
              onClick={async () => {
                /* "Submitted" is the server's word, not ours. It used to say so the moment the
                   button was pressed, whether or not anything had been sent -- which is the
                   worst possible lie on a form somebody fills in to get help. */
                if (!ok(step)) return;
                setSending(true);
                setFailed('');
                try {
                  await onSubmit?.();
                } catch (err) {
                  setFailed(err.message || 'Sorry — that did not go through. Please try again.');
                  setSending(false);
                  return;
                }
                setSending(false);
                setDone(true);
                scrollToId(anchor);
              }}
            >
              {sending ? 'Sending…' : submitLabel}
            </ArrowButton>
          ) : (
            <ArrowButton onClick={() => { if (ok(step)) go(step + 1); }}>Continue</ArrowButton>
          )}
        </div>
        {failed && <p className="fine fine-err" role="alert">{failed}</p>}
        {fine && <p className="fine">{fine}</p>}
      </div>

      <div className="form-done" hidden={!done}>
        <div className="done-box">
          <div className="big-check"><Icon name="check" sw={2.6} /></div>
          <h3 className="q">{doneView.title}</h3>
          <p className="qs" style={{ maxWidth: doneView.maxWidth, margin: '0 auto 26px' }}>{doneView.text}</p>
          <button
            type="button"
            className="btn btn-o"
            onClick={() => {
              setStep(0);
              setDone(false);
            }}
          >
            {doneView.reset}
          </button>
        </div>
      </div>
    </Reveal>
  );
}

/** Shared question header for a step. */
export function Q({ title, sub, subStyle }) {
  return (
    <>
      <h3 className="q">{title}</h3>
      <p className="qs" style={subStyle}>{sub}</p>
    </>
  );
}

/** Labelled text input bound to form data by name. `error` is the message to show under it. */
export function Field({ id, label, name, data, set, full, as = 'input', error, req, hint, ...rest }) {
  const Tag = as;
  return (
    <div className={cx('fld', full && 'full', error && 'err')}>
      <label htmlFor={id}>{label}{req && <b> *</b>}</label>
      <Tag id={id} name={name} value={data[name] ?? ''} aria-invalid={!!error}
           onChange={(e) => set(name, e.target.value)} {...rest} />
      {hint && !error && <span className="ph-hint">{hint}</span>}
      <span className="emsg">{error}</span>
    </div>
  );
}

/** A row of chips with a label and its own error line -- Chips alone has nowhere to say what is wrong. */
export function ChipsField({ label, error, req, children }) {
  return (
    <div className={cx('chips-fld', error && 'err')}>
      {label && <p className="ql">{label}{req && <b className="req"> *</b>}</p>}
      {children}
      {error && <span className="emsg">{error}</span>}
    </div>
  );
}
