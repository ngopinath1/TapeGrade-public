import { useId, useRef, type ReactNode } from "react";

export function SectionTabs({
  label,
  tabs,
  selected,
  onSelect,
  children,
}: {
  label: string;
  tabs: { id: string; label: string }[];
  selected: string;
  onSelect: (id: string) => void;
  children: (id: string) => ReactNode;
}) {
  const prefix = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <>
      <div className="section-tabs" role="tablist" aria-label={label}>
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            role="tab"
            id={`${prefix}-tab-${tab.id}`}
            aria-selected={selected === tab.id}
            aria-controls={`${prefix}-panel-${tab.id}`}
            tabIndex={selected === tab.id ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => {
              if (event.altKey || event.ctrlKey || event.metaKey) return;
              let next = index;
              if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
              else if (event.key === "ArrowLeft")
                next = (index - 1 + tabs.length) % tabs.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = tabs.length - 1;
              else return;
              event.preventDefault();
              onSelect(tabs[next].id);
              buttons.current[next]?.focus();
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`${prefix}-panel-${tab.id}`}
          aria-labelledby={`${prefix}-tab-${tab.id}`}
          hidden={selected !== tab.id}
          tabIndex={0}
        >
          {children(tab.id)}
        </div>
      ))}
    </>
  );
}
