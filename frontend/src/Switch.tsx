import { useId } from 'preact/hooks';

interface SwitchProps {
  on: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
}

/** Just the toggle; name it with `labelledBy` (an element id) or `label` (text for screen readers). */
export function SwitchButton({ on, onChange, disabled, labelledBy, label }: SwitchProps & { labelledBy?: string; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-labelledby={labelledBy} aria-label={label} class={on ? 'switch on' : 'switch'} disabled={disabled} onClick={() => onChange(!on)}>
      <span class="knob" />
    </button>
  );
}

/** A settings row: the label on the left, the toggle on the right. */
export function Switch({ label, ...props }: SwitchProps & { label: string }) {
  const labelId = useId(); // ids can't contain spaces, so not derived from the label text
  return (
    <div class="setting">
      <span id={labelId}>{label}</span>
      <SwitchButton {...props} labelledBy={labelId} />
    </div>
  );
}
