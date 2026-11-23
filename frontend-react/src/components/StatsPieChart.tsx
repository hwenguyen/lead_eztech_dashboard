import React, { useMemo } from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface StatsPieChartProps {
  title: string;
  subtitle?: string;
  stats: Record<string, number> | undefined;
  colorMap?: Record<string, string>;
  unit?: string;
  headerAction?: React.ReactNode;
  selectedKey?: string | null;
  onSelectKey?: (key: string | null) => void;
}

const COLORS = ['#1E5BD6', 'var(--ez-chart-navy)', '#F5B400', '#3B82F6', '#64748B', '#10B981', '#94A3B8', '#CBD5E1'];
// Light-luminance slices need dark ink to satisfy WCAG AA contrast
const LIGHT_SLICE_COLORS = new Set(['#F5B400', '#FFC107', '#CBD5E1', '#94A3B8']);

const CustomLabel = ({
  cx,
  cy,
  midAngle,
  innerRadius,
  outerRadius,
  percent,
  fill,
}: {
  cx?: number;
  cy?: number;
  midAngle?: number;
  innerRadius?: number;
  outerRadius?: number;
  percent?: number;
  fill?: string;
}) => {
  if (!percent || percent < 0.06 || cx === undefined || cy === undefined || midAngle === undefined || innerRadius === undefined || outerRadius === undefined) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  const textFill = fill && LIGHT_SLICE_COLORS.has(fill.toUpperCase()) ? '#0A1F44' : '#FFFFFF';
  return (
    <text x={x} y={y} fill={textFill} textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={700}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
};

const StatsPieTooltip = ({ active, payload, unit, total, selectedKey, clickable }: any) => {
  if (!active || !payload || !payload.length) return null;
  const item = payload[0]?.payload;
  const name = String(item?.name ?? payload[0]?.name ?? '');
  const val = Number(payload[0]?.value || 0);
  const share = total > 0 ? ((val / total) * 100).toFixed(1) : '0.0';
  const swatch = item?.color || payload[0]?.color || '#1E5BD6';
  const isSelected = Boolean(selectedKey && selectedKey === name);

  return (
    <div
      className="backdrop-blur-md border rounded-xl shadow-card-hover px-3 py-2.5 text-xs min-w-[175px] max-w-[240px]"
      style={{
        backgroundColor: 'var(--ez-tooltip-bg)',
        borderColor: 'var(--ez-tooltip-border)',
        color: 'var(--ez-text)',
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="flex items-center gap-1.5 font-semibold text-navy truncate">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: swatch }} />
          <span className="truncate">{name}</span>
        </span>
        {isSelected && (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-eztech-light text-eztech shrink-0">
            Đang lọc
          </span>
        )}
      </div>
      <div className="font-mono font-bold text-navy tabular-nums">
        {val.toLocaleString()} {unit} <span className="text-slate-400 font-normal">({share}%)</span>
      </div>
      {clickable && (
        <div className="mt-1 pt-1 border-t border-slate-100/70 text-[10px] text-slate-400">
          {isSelected ? 'Nhấn lại để bỏ lọc' : 'Nhấn để lọc theo mục này'}
        </div>
      )}
    </div>
  );
};

export const StatsPieChart = React.memo(function StatsPieChart({
  title,
  subtitle,
  stats,
  colorMap,
  unit = 'Lead',
  headerAction,
  selectedKey,
  onSelectKey,
}: StatsPieChartProps) {
  const { data, total } = useMemo(() => {
    if (!stats) return { data: [], total: 0 };
    const entries = Object.entries(stats)
      .filter(([, value]) => value > 0)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .map((item, index) => ({
        ...item,
        color: colorMap && colorMap[item.name] ? colorMap[item.name] : COLORS[index % COLORS.length],
      }));
    const sum = entries.reduce((acc, curr) => acc + curr.value, 0);
    return { data: entries, total: sum };
  }, [stats, colorMap]);

  const handleToggle = (name: string) => {
    if (!onSelectKey) return;
    onSelectKey(selectedKey === name ? null : name);
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
        </div>
        {headerAction && (
          <div className="shrink-0">
            {headerAction}
          </div>
        )}
      </div>

      {data.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={170}>
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={42}
                outerRadius={76}
                paddingAngle={2}
                dataKey="value"
                labelLine={false}
                label={(props) => (
                  <CustomLabel {...props} fill={data[props.index]?.color} />
                )}
                animationDuration={250}
                onClick={(_, index) => {
                  const item = data[index];
                  if (item) handleToggle(item.name);
                }}
              >
                {data.map((item) => {
                  const isActive = !selectedKey || selectedKey === item.name;
                  return (
                    <Cell
                      key={item.name}
                      fill={item.color}
                      fillOpacity={isActive ? 1 : 0.25}
                      stroke={selectedKey === item.name ? 'var(--ez-card)' : 'none'}
                      strokeWidth={selectedKey === item.name ? 2 : 0}
                      style={{ cursor: onSelectKey ? 'pointer' : 'default' }}
                    />
                  );
                })}
              </Pie>
              <Tooltip
                content={
                  <StatsPieTooltip
                    unit={unit}
                    total={total}
                    selectedKey={selectedKey}
                    clickable={!!onSelectKey}
                  />
                }
              />
            </PieChart>
          </ResponsiveContainer>

          <div className="mt-3 pt-3 border-t border-slate-100 max-h-[116px] overflow-y-auto space-y-1 pr-1 custom-scrollbar">
            {data.map((item) => {
              const isSelected = selectedKey === item.name;
              const isDimmed = Boolean(selectedKey && !isSelected);
              return (
                <button
                  key={item.name}
                  type="button"
                  onClick={() => handleToggle(item.name)}
                  disabled={!onSelectKey}
                  aria-pressed={onSelectKey ? isSelected : undefined}
                  className={`w-full flex items-center justify-between text-xs py-1 px-1.5 -mx-1.5 rounded-md transition-all text-left ${
                    onSelectKey ? 'cursor-pointer hover:bg-slate-50' : ''
                  } ${isSelected ? 'bg-eztech-light font-semibold text-eztech' : ''} ${
                    isDimmed ? 'opacity-45' : ''
                  }`}
                >
                  <span title={item.name} className="flex items-center gap-2 text-slate-600 truncate mr-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block shrink-0"
                      style={{ backgroundColor: item.color }}
                    />
                    <span className={`truncate ${isSelected ? 'text-navy font-semibold' : ''}`}>{item.name}</span>
                  </span>
                  <span className="font-mono font-semibold text-navy shrink-0 tabular-nums">
                    {item.value.toLocaleString()}
                    <span className="text-slate-400 font-normal ml-1">
                      ({total > 0 ? ((item.value / total) * 100).toFixed(1) : '0.0'}%)
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      ) : (
        <div className="flex items-center justify-center h-[200px] text-slate-400 text-xs">
          Không có dữ liệu
        </div>
      )}
    </div>
  );
});
