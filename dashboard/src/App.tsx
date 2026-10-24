import { useEffect, useState } from "react";
import {
  CalendarDays,
  ChartNoAxesColumnIncreasing,
  ChevronDown,
  CircleDot,
  Clock3,
  CodeXml,
  Database,
  Flame,
  GitCommitHorizontal,
  GitPullRequest,
  Github,
  RefreshCw,
  Star,
  Trophy,
  UsersRound,
} from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";

type DashboardData = {
  username: string;
  generatedAt: string;
  stats: {
    stars: number;
    commits: number;
    prs: number;
    issues: number;
    contributedTo: number;
  };
  streak: {
    total: number;
    current: number;
    longest: number;
    firstDate: string;
    lastDate: string;
  };
  languages: { name: string; pct: number }[];
};

const languageColors: Record<string, string> = {
  JavaScript: "#FACC15",
  TypeScript: "#2563EB",
  Java: "#D97706",
  HTML: "#EF4444",
  CSS: "#9333EA",
  Other: "#F472B6",
};

const statRows = [
  { key: "stars", label: "Total Stars Earned", icon: Star, tone: "amber" },
  {
    key: "commits",
    label: "Total Commits (last year)",
    icon: GitCommitHorizontal,
    tone: "emerald",
  },
  { key: "prs", label: "Total PRs", icon: GitPullRequest, tone: "violet" },
  { key: "issues", label: "Total Issues", icon: CircleDot, tone: "rose" },
  {
    key: "contributedTo",
    label: "Contributed to (last year)",
    icon: UsersRound,
    tone: "blue",
  },
] as const;

function isDashboardData(value: unknown): value is DashboardData {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<DashboardData>;
  const isCount = (number: unknown) =>
    typeof number === "number" && Number.isFinite(number) && number >= 0;
  return (
    typeof data.username === "string" &&
    typeof data.generatedAt === "string" &&
    !!data.stats &&
    ["stars", "commits", "prs", "issues", "contributedTo"].every((key) =>
      isCount(data.stats?.[key as keyof DashboardData["stats"]]),
    ) &&
    !!data.streak &&
    ["total", "current", "longest"].every((key) =>
      isCount(data.streak?.[key as keyof DashboardData["streak"]]),
    ) &&
    typeof data.streak.firstDate === "string" &&
    typeof data.streak.lastDate === "string" &&
    Array.isArray(data.languages) &&
    data.languages.every(
      (language) =>
        !!language &&
        typeof language === "object" &&
        typeof language.name === "string" &&
        isCount(language.pct) &&
        language.pct <= 100,
    )
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function CardHeading({
  icon: Icon,
  title,
  subtitle,
  tone = "blue",
  trailing,
}: {
  icon: typeof Github;
  title: React.ReactNode;
  subtitle: string;
  tone?: string;
  trailing?: React.ReactNode;
}) {
  return (
    <div className="card-heading">
      <span className={`heading-icon ${tone}`} aria-hidden="true">
        <Icon size={23} strokeWidth={2.2} />
      </span>
      <div className="heading-copy">
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
      {trailing}
    </div>
  );
}

function StatCard({ data }: { data: DashboardData }) {
  return (
    <article className="glass-card stats-card">
      <CardHeading
        icon={Github}
        title={
          <>
            PavanVeguru’s <span>GitHub Stats</span>
          </>
        }
        subtitle="A quick summary of my GitHub activity"
        tone="github"
      />
      <dl className="stats-list">
        {statRows.map(({ key, label, icon: Icon, tone }) => (
          <div className="stat-row" key={key}>
            <span className={`stat-icon ${tone}`} aria-hidden="true">
              <Icon size={19} strokeWidth={2.5} />
            </span>
            <dt>{label}</dt>
            <dd className={tone}>{formatCount(data.stats[key])}</dd>
          </div>
        ))}
      </dl>
      <footer className="card-footer">
        <Clock3 size={18} aria-hidden="true" />
        <span>
          Updated {formatDate(data.generatedAt)} <i>·</i> Generated from live
          GitHub data
        </span>
      </footer>
    </article>
  );
}

function StreakRing({ current }: { current: number }) {
  return (
    <div className="streak-ring">
      <svg
        className="ring-svg"
        viewBox="0 0 220 220"
        role="img"
        aria-label={`${current} day current GitHub streak`}
      >
        <defs>
          <linearGradient id="ring-gradient" x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#22D3EE" />
            <stop offset="100%" stopColor="#2563EB" />
          </linearGradient>
          <filter id="ring-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>
        <circle className="ring-track" cx="110" cy="110" r="91" />
        <motion.circle
          className="ring-progress"
          cx="110"
          cy="110"
          r="91"
          pathLength="100"
          initial={{ strokeDashoffset: 100 }}
          animate={{ strokeDashoffset: 22 }}
          transition={{ duration: 1.25, ease: "easeOut", delay: 0.35 }}
        />
      </svg>
      <div className="ring-content">
        <span className="flame-bubble">
          <Flame size={31} fill="currentColor" strokeWidth={1.5} aria-hidden="true" />
        </span>
        <strong>{current}</strong>
        <span>Current Streak</span>
      </div>
    </div>
  );
}

function MiniMetric({
  icon: Icon,
  value,
  label,
  tone,
}: {
  icon: typeof UsersRound;
  value: number;
  label: string;
  tone: string;
}) {
  return (
    <div className="mini-metric">
      <span className={`metric-icon ${tone}`} aria-hidden="true">
        <Icon size={23} fill="currentColor" strokeWidth={1.7} />
      </span>
      <strong className={tone}>{formatCount(value)}</strong>
      <span>{label}</span>
    </div>
  );
}

function StreakCard({ data }: { data: DashboardData }) {
  return (
    <article className="glass-card streak-card">
      <CardHeading
        icon={ChartNoAxesColumnIncreasing}
        title="Contribution / Streak"
        subtitle="My GitHub contributions and streak details"
        trailing={
          <label className="range-select">
            <span className="sr-only">Contribution period</span>
            <select defaultValue="year" aria-label="Contribution period">
              <option value="year">Last 1 year</option>
            </select>
            <ChevronDown size={15} aria-hidden="true" />
          </label>
        }
      />
      <div className="streak-content">
        <MiniMetric
          icon={UsersRound}
          value={data.streak.total}
          label="Total Contributions"
          tone="blue"
        />
        <StreakRing current={data.streak.current} />
        <MiniMetric
          icon={Trophy}
          value={data.streak.longest}
          label="Longest Streak"
          tone="gold"
        />
      </div>
      <footer className="card-footer">
        <CalendarDays size={18} aria-hidden="true" />
        <span>
          GitHub contribution calendar <i>·</i> {data.streak.firstDate} →{" "}
          {data.streak.lastDate}
        </span>
      </footer>
    </article>
  );
}

function LanguagesCard({ data }: { data: DashboardData }) {
  return (
    <article className="glass-card languages-card">
      <CardHeading
        icon={CodeXml}
        title="Most Used Languages"
        subtitle="By bytes of code in my repositories"
      />
      <div
        className="language-bar"
        role="img"
        aria-label={`Language usage: ${data.languages
          .map(({ name, pct }) => `${name} ${pct.toFixed(2)}%`)
          .join(", ")}`}
      >
        {data.languages.map(({ name, pct }) => (
          <span
            key={name}
            style={{
              backgroundColor: languageColors[name] ?? "#94A3B8",
              width: `${pct}%`,
            }}
          />
        ))}
      </div>
      <ul className="language-list">
        {data.languages.map(({ name, pct }) => (
          <li key={name}>
            <span
              className="language-dot"
              style={{ backgroundColor: languageColors[name] ?? "#94A3B8" }}
              aria-hidden="true"
            />
            <span>{name}</span>
            <strong style={{ color: languageColors[name] ?? "#475569" }}>
              {pct.toFixed(2)}%
            </strong>
          </li>
        ))}
      </ul>
      <footer className="card-footer">
        <Database size={18} aria-hidden="true" />
        <span>
          By bytes of code <i>·</i> owned repositories only (forks excluded)
          <br />
          Updated {formatDate(data.generatedAt)}
        </span>
      </footer>
    </article>
  );
}

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const controller = new AbortController();

    async function loadDashboard() {
      try {
        const response = await fetch(`${import.meta.env.BASE_URL}stats.json`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`GitHub stats could not be loaded (${response.status}).`);
        }
        const payload: unknown = await response.json();
        if (!isDashboardData(payload)) {
          throw new Error("The generated GitHub stats have an invalid format.");
        }
        setData(payload);
        setError(null);
      } catch (loadError) {
        if (loadError instanceof DOMException && loadError.name === "AbortError") {
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "An unexpected error occurred while loading GitHub stats.",
        );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    void loadDashboard();
    return () => controller.abort();
  }, []);

  if (loading) {
    return (
      <main className="page-shell">
        <div className="loading-state" role="status">
          <RefreshCw size={18} className="spin" aria-hidden="true" />
          Loading live GitHub stats…
        </div>
      </main>
    );
  }

  if (error || !data) {
    return (
      <main className="page-shell">
        <div className="error-state" role="alert">
          <span>{error ?? "GitHub stats are currently unavailable."}</span>
          <button onClick={() => window.location.reload()}>Try again</button>
        </div>
      </main>
    );
  }

  return (
    <main className="page-shell">
      <motion.section
        className="dashboard-grid"
        aria-label="GitHub statistics dashboard"
        initial={reduceMotion ? false : "hidden"}
        animate="visible"
        variants={{
          hidden: {},
          visible: { transition: { staggerChildren: 0.14 } },
        }}
      >
        {[
          <StatCard key="stats" data={data} />,
          <StreakCard key="streak" data={data} />,
          <LanguagesCard key="languages" data={data} />,
        ].map((card) => (
          <motion.div
            key={card.key}
            className="card-motion"
            variants={{
              hidden: { opacity: 0, y: 18 },
              visible: {
                opacity: 1,
                y: 0,
                transition: { duration: 0.55, ease: "easeOut" },
              },
            }}
          >
            {card}
          </motion.div>
        ))}
      </motion.section>
    </main>
  );
}
