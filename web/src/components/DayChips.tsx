const DAYS: { iso: number; label: string }[] = [
  { iso: 1, label: "M" },
  { iso: 2, label: "T" },
  { iso: 3, label: "W" },
  { iso: 4, label: "T" },
  { iso: 5, label: "F" },
  { iso: 6, label: "S" },
  { iso: 7, label: "S" },
];

/** ISO weekday chips (1=Mon..7=Sun). An empty selection means "one-shot"
 * (`core/scheduler.py`'s `Alarm.days == set()`), so this never forces at
 * least one day to be picked. */
export function DayChips({
  selected,
  onChange,
}: {
  selected: number[];
  onChange: (days: number[]) => void;
}): JSX.Element {
  const toggle = (iso: number) => {
    onChange(
      selected.includes(iso) ? selected.filter((d) => d !== iso) : [...selected, iso].sort()
    );
  };
  return (
    <div className="day-chips" role="group" aria-label="Repeat on days">
      {DAYS.map((day) => (
        <button
          key={day.iso}
          type="button"
          className={`day-chip${selected.includes(day.iso) ? " day-chip--on" : ""}`}
          aria-pressed={selected.includes(day.iso)}
          onClick={() => toggle(day.iso)}
        >
          {day.label}
        </button>
      ))}
    </div>
  );
}
