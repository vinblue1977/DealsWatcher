import { useId } from 'preact/hooks';

export function Switch({ on, label, onChange, disabled }: { on: boolean; label: string; onChange: (on: boolean) => void; disabled?: boolean }) {
  const labelId = useId(); // ids can't contain spaces, so not derived from the label text
  return (
    <div class="setting">
      <span id={labelId}>{label}</span>
      <button type="button" role="switch" aria-checked={on} aria-labelledby={labelId} class={on ? 'switch on' : 'switch'} disabled={disabled} onClick={() => onChange(!on)}>
        <span class="knob" />
      </button>
    </div>
  );
}
