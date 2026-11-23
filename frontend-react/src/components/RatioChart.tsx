import React, { useMemo } from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface RatioChartProps {
  newLeads: number;
  recontactLeads: number;
  totalLeads: number;
  newPhoneLeads: number;
  selectedLeadType?: 'new' | 'recontact' | null;
  onSelectLeadType?: (leadType: 'new' | 'recontact' | null) => void;
}

const CustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }: {
  cx?: number;
  cy?: number;
  midAngle?: number;
  innerRadius?: number;
  outerRadius?: number;
  percent?: number;
}) => {
  if (!percent || percent < 0.05 || cx === undefined || cy === undefined || midAngle === undefined || innerRadius === undefined || outerRadius === undefined) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
};

const RatioTooltip = ({ active, payload, total, selectedLeadType, clickable }: any) => {
  if (!active || !payload || !payload.length) return null;
  const item = payload[0]?.payload;
  const val = Number(payload[0]?.value || 0);
  const share = total > 0 ? ((val / total) * 100).toFixed(1) : '0.0';
  const isSelected = Boolean(selectedLeadType && item?.key === selectedLeadType);

  return (
    <div
      className="backdrop-blur-md border rounded-xl shadow-card-hover px-3 py-2.5 text-xs min-w-[165px]"
      style={{
        backgroundColor: 'var(--ez-tooltip-bg)',
        borderColor: 'var(--ez-tooltip-border)',
        color: 'var(--ez-text)',
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="flex items-center gap-1.5 font-semibold text-navy">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: item?.color }} />
          {item?.name}
        </span>
        {isSelected && (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-eztech-light text-eztech">
            Đang lọc
          </span>
        )}
      </div>
      <div className="font-mono font-bold text-navy tabular-nums">
        {val.toLocaleString()} Lead <span className="text-slate-400 font-normal">({share}%)</span>
      </div>
      {clickable && (
        <div className="mt-1 pt-1 border-t border-slate-100/70 text-[10px] text-slate-400">
          {isSelected ? 'Nhấn lại để bỏ lọc' : 'Nhấn để lọc nhóm này'}
        </div>
      )}
    </div>
  );
};

export const RatioChart = React.memo(function RatioChart({
  newLeads,
  recontactLeads,
  totalLeads,
  newPhoneLeads,
  selectedLeadType,
  onSelectLeadType,
}: RatioChartProps) {
  const data = useMemo(
    () =>
      [
        { key: 'new' as const, name: 'Lead Mới', value: newLeads, color: '#1E5BD6' },
        { key: 'recontact' as const, name: 'Contact Lại', value: recontactLeads, color: 'var(--ez-chart-navy)' },
      ].filter((d) => d.value > 0),
    [newLeads, recontactLeads]
  );

  const sliceTotal = data.reduce((acc, d) => acc + d.value, 0);
  const newRate = totalLeads > 0 ? ((newLeads / totalLeads) * 100).toFixed(1) : '0.0';
  const recontactRate = totalLeads > 0 ? ((recontactLeads / totalLeads) * 100).toFixed(1) : '0.0';
  const phoneRate = newLeads > 0 ? ((newPhoneLeads / newLeads) * 100).toFixed(1) : '0.0';

  const handleToggleType = (typeKey: 'new' | 'recontact') => {
    if (!onSelectLeadType) return;
    onSelectLeadType(selectedLeadType === typeKey ? null : typeKey);
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card h-full flex flex-col justify-between">
      <div className="mb-3">
        <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">Tỉ lệ chuyển đổi</h3>
      </div>

      {data.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={160}>
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={44}
                outerRadius={72}
                paddingAngle={3}
                dataKey="value"
                labelLine={false}
                label={<CustomLabel />}
                animationDuration={250}
                onClick={(_, index) => {
                  const item = data[index];
                  if (item) handleToggleType(item.key);
                }}
              >
                {data.map((item) => {
                  const isActive = !selectedLeadType || selectedLeadType === item.key;
                  return (
                    <Cell
                      key={item.key}
                      fill={item.color}
                      fillOpacity={isActive ? 1 : 0.25}
                      stroke={selectedLeadType === item.key ? 'var(--ez-card)' : 'none'}
                      strokeWidth={selectedLeadType === item.key ? 2 : 0}
                      style={{ cursor: onSelectLeadType ? 'pointer' : 'default' }}
                    />
                  );
                })}
              </Pie>
              <Tooltip
                content={
                  <RatioTooltip
                    total={sliceTotal}
                    selectedLeadType={selectedLeadType}
                    clickable={!!onSelectLeadType}
                  />
                }
              />
            </PieChart>
          </ResponsiveContainer>

          <div className="mt-3 pt-3 border-t border-slate-100 space-y-1.5">
            <button
              type="button"
              onClick={() => handleToggleType('new')}
              disabled={!onSelectLeadType}
              aria-pressed={onSelectLeadType ? selectedLeadType === 'new' : undefined}
              className={`w-full flex items-center justify-between text-xs rounded-md px-1.5 py-0.5 -mx-1.5 transition-colors ${
                onSelectLeadType ? 'cursor-pointer hover:bg-slate-50' : ''
              } ${selectedLeadType === 'new' ? 'bg-eztech-light font-semibold text-eztech' : ''}`}
            >
              <span className="flex items-center gap-2 text-slate-600">
                <span className="w-2 h-2 rounded-full bg-eztech inline-block" />
                Tỉ lệ Lead Mới
              </span>
              <span className="font-mono font-semibold text-navy tabular-nums">{newRate}%</span>
            </button>
            <button
              type="button"
              onClick={() => handleToggleType('recontact')}
              disabled={!onSelectLeadType}
              aria-pressed={onSelectLeadType ? selectedLeadType === 'recontact' : undefined}
              className={`w-full flex items-center justify-between text-xs rounded-md px-1.5 py-0.5 -mx-1.5 transition-colors ${
                onSelectLeadType ? 'cursor-pointer hover:bg-slate-50' : ''
              } ${selectedLeadType === 'recontact' ? 'bg-eztech-light font-semibold text-eztech' : ''}`}
            >
              <span className="flex items-center gap-2 text-slate-600">
                <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: 'var(--ez-chart-navy)' }} />
                Tỉ lệ Contact Lại
              </span>
              <span className="font-mono font-semibold text-navy tabular-nums">{recontactRate}%</span>
            </button>
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-2 text-slate-600">
                <span className="w-2 h-2 rounded-full bg-gold inline-block" />
                SĐT / Tạo mới
              </span>
              <span className="font-mono font-bold text-gold-dark tabular-nums">{phoneRate}%</span>
            </div>
            <div className="h-px bg-slate-100 my-1.5" />
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 font-medium">Tổng Lead</span>
              <span className="font-mono font-bold text-navy tabular-nums">{totalLeads.toLocaleString()}</span>
            </div>
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
