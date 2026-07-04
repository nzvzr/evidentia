interface LogoProps {
  /** square size in px */
  size?: number;
  /** show the "Evidentia" wordmark next to the mark */
  showWordmark?: boolean;
  /** wordmark color; defaults to currentColor */
  wordmarkColor?: string;
  className?: string;
}

/**
 * Evidentia logo: black rounded square with a lowercase white "e"
 * and a small white dot in the top-right corner.
 */
export default function Logo({
  size = 28,
  showWordmark = false,
  wordmarkColor,
  className,
}: LogoProps) {
  const dot = Math.max(2.5, size * 0.1);
  const dotTop = size * 0.22;
  const dotRight = size * 0.18;
  return (
    <div className={className} style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div
        style={{
          width: size,
          height: size,
          background: "#0a0a0b",
          borderRadius: Math.round(size * 0.22),
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          flex: "none",
        }}
      >
        <span
          style={{
            fontWeight: 700,
            fontSize: size * 0.58,
            lineHeight: 1,
            color: "#fff",
          }}
        >
          e
        </span>
        <span
          style={{
            position: "absolute",
            top: dotTop,
            right: dotRight,
            width: dot,
            height: dot,
            borderRadius: "50%",
            background: "#fff",
          }}
        />
      </div>
      {showWordmark && (
        <span
          style={{
            fontWeight: 700,
            fontSize: Math.max(14, size * 0.55),
            letterSpacing: "-0.01em",
            color: wordmarkColor,
          }}
        >
          Evidentia
        </span>
      )}
    </div>
  );
}
