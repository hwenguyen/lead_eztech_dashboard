import React, { useId } from 'react';
import {
  AreaChart, Area, BarChart, Bar, Cell, ReferenceLine,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import { X } from 'lucide-react';
import type { TrendData } from '../services/api';

interface TrendChartProps {
  data: TrendData[];
  selectedDate?: string | null;
  onSelectDate?: (date: string | null) => void;
}

const WEEKDAYS_VI = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];

const formatAxisDate = (iso: string) => {
  if (iso && iso.length >= 10 && iso[4] === '-' && iso[7] === '-') {
    return `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
  }
  return iso;
};

const formatTooltipDate = (iso: string) => {
  if (iso && iso.length >= 10 && iso[4] === '-' && iso[7] === '-') {
    const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
    const dayPrefix = !isNaN(dt.getTime()) ? `${WEEKDAYS_VI[dt.getDay()]}, ` : '';
    return `${dayPrefix}${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
  }
  return iso;
};

const renderSeriesDot = (color: string, selectedDate: string | null | undefined, totalPoints: number) =>
  (props: any) => {
    const { cx, cy, payload, index } = props;
    if (cx == null || cy == null) return <g key={`empty-${index}`} />;
    const isSelected = Boolean(selectedDate && payload?.date === selectedDate);
    const radius = isSelected ? 4.5 : totalPoints === 1 ? 4 : 0;
    return (
      <circle
        key={`${payload?.date || index}-${color}`}
        cx={cx}
        cy={cy}
        r={radius}
        fill={color}
        stroke="var(--ez-card)"
        strokeWidth={isSelected ? 2 : 0}
      />
    );
  };

const CustomTooltip = ({ active, payload, label, selectedDate, clickable }: any) => {
  if (!active || !payload || !payload.length) return null;

  const row: Partial<TrendData> = payload[0]?.payload || {};
  const newLeads = Number(row.new_leads || 0);
  const recontactLeads = Number(row.recontact_leads || 0);
  const phoneLeads = Number(row.phone_leads || 0);
  const totalDay = newLeads + recontactLeads;
  const pctOfDay = (val: number) => (totalDay > 0 ? ((val / totalDay) * 100).toFixed(1) : '0.0');
  const isSelected = Boolean(selectedDate && label === selectedDate);

  return (
    <div
      className="backdrop-blur-md border rounded-xl shadow-card-hover p-3 text-xs min-w-[210px]"
      style={{
        backgroundColor: 'var(--ez-tooltip-bg)',
        borderColor: 'var(--ez-tooltip-border)',
        color: 'var(--ez-text)',
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-slate-200/70">
        <span className="font-mono font-semibold text-navy">{formatTooltipDate(String(label || ''))}</span>
        {isSelected && (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-eztech-light text-eztech border border-eztech-border">
            Đang lọc
          </span>
        )}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-4 pb-1 border-b border-slate-100/70">
          <span className="font-semibold text-navy">Tổng Lead</span>
          <span className="font-mono font-bold text-navy tabular-nums">{totalDay.toLocaleString()}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="w-2 h-2 rounded-full bg-eztech shrink-0" />
            Lead Mới
          </span>
          <span className="font-mono font-semibold text-navy tabular-nums">
            {newLeads.toLocaleString()}
            <span className="text-slate-400 font-normal ml-1">({pctOfDay(newLeads)}%)</span>
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: 'var(--ez-chart-navy)' }} />
            Contact Lại
          </span>
          <span className="font-mono font-semibold text-navy tabular-nums">
            {recontactLeads.toLocaleString()}
            <span className="text-slate-400 font-normal ml-1">({pctOfDay(recontactLeads)}%)</span>
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="w-2 h-2 rounded-full bg-gold shrink-0" />
            SĐT thu được
          </span>
          <span className="font-mono font-semibold text-gold-dark tabular-nums">
            {phoneLeads.toLocaleString()}
            <span className="text-slate-400 font-normal ml-1">({pctOfDay(phoneLeads)}%)</span>
          </span>
        </div>
      </div>

      {clickable && (
        <div className="mt-2 pt-1.5 border-t border-slate-100/70 text-[10px] text-slate-400">
          {isSelected ? 'Nhấn lại để bỏ lọc ngày' : 'Nhấn để lọc theo ngày này'}
        </div>
      )}
    </div>
  );
};

export const TrendChart = React.memo(function TrendChart({ data, selectedDate, onSelectDate }: TrendChartProps) {
  const uid = useId().replace(/:/g, '');
  const gradNew = `colorNew-${uid}`;
  const gradContact = `colorContact-${uid}`;
  const gradPhone = `colorPhone-${uid}`;

  const handleChartClick = (state: any) => {
    if (!onSelectDate) return;
    const clicked = state?.activePayload?.[0]?.payload?.date || state?.activeLabel;
    if (clicked) {
      const clickedStr = String(clicked);
      onSelectDate(selectedDate === clickedStr ? null : clickedStr);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 h-full">
      {/* Area Chart - chiếm 2/3 */}
      <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200/80 p-5 shadow-card h-full flex flex-col justify-between">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-5">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">Xu hướng Lead theo thời gian</h3>
            {selectedDate && onSelectDate && (
              <button
                type="button"
                onClick={() => onSelectDate(null)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-eztech-light text-eztech border border-eztech-border hover:bg-eztech-border/50 transition-colors cursor-pointer"
                title="Bỏ lọc ngày"
              >
                <span className="font-mono">{formatAxisDate(selectedDate)}</span>
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-3.5 text-[11px] font-medium text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-eztech inline-block" />
              Lead Mới
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: 'var(--ez-chart-navy)' }} />
              Contact Lại
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-gold inline-block" />
              SĐT thu được
            </span>
          </div>
        </div>
        {data.length > 0 ? (
          <ResponsiveContainer width="100%" height={245}>
            <AreaChart
              data={data}
              margin={{ top: 5, right: 8, left: -12, bottom: 0 }}
              onClick={handleChartClick}
              style={{ cursor: onSelectDate ? 'pointer' : 'default' }}
            >
              <defs>
                <linearGradient id={gradNew} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#1E5BD6" stopOpacity={0.16} />
                  <stop offset="95%" stopColor="#1E5BD6" stopOpacity={0} />
                </linearGradient>
                <linearGradient id={gradContact} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--ez-chart-navy)" stopOpacity={0.14} />
                  <stop offset="95%" stopColor="var(--ez-chart-navy)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id={gradPhone} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#F5B400" stopOpacity={0.18} />
                  <stop offset="95%" stopColor="#F5B400" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tickFormatter={formatAxisDate} stroke="var(--ez-chart-axis)" fontSize={11} tickLine={false} axisLine={false} />
              <YAxis allowDecimals={false} stroke="var(--ez-chart-axis)" fontSize={11} tickLine={false} axisLine={false} />
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--ez-chart-grid)" />
              {selectedDate && (
                <ReferenceLine x={selectedDate} stroke="#1E5BD6" strokeDasharray="3 3" strokeWidth={1.5} />
              )}
              <Tooltip content={<CustomTooltip selectedDate={selectedDate} clickable={!!onSelectDate} />} />
              <Area
                type="monotone"
                name="Lead Mới"
                dataKey="new_leads"
                stroke="#1E5BD6"
                strokeWidth={2}
                fillOpacity={1}
                fill={`url(#${gradNew})`}
                dot={renderSeriesDot('#1E5BD6', selectedDate, data.length)}
                activeDot={{ r: 5, strokeWidth: 2, cursor: 'pointer' }}
                animationDuration={250}
              />
              <Area
                type="monotone"
                name="Lead Contact Lại"
                dataKey="recontact_leads"
                stroke="var(--ez-chart-navy)"
                strokeWidth={1.75}
                fillOpacity={1}
                fill={`url(#${gradContact})`}
                dot={renderSeriesDot('var(--ez-chart-navy)', selectedDate, data.length)}
                activeDot={{ r: 5, strokeWidth: 2, cursor: 'pointer' }}
                animationDuration={250}
              />
              <Area
                type="monotone"
                name="SĐT thu được"
                dataKey="phone_leads"
                stroke="#F5B400"
                strokeWidth={2}
                fillOpacity={1}
                fill={`url(#${gradPhone})`}
                dot={renderSeriesDot('#F5B400', selectedDate, data.length)}
                activeDot={{ r: 5, strokeWidth: 2, cursor: 'pointer' }}
                animationDuration={250}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-[245px] text-slate-400 text-xs">
            Chưa có dữ liệu xu hướng trong kỳ này
          </div>
        )}
      </div>

      {/* Bar Chart - chiếm 1/3 */}
      <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card h-full flex flex-col justify-between">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-5">
          <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">So sánh theo ngày</h3>
          <div className="flex items-center gap-2.5 text-[10px] font-medium text-slate-500">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-eztech inline-block" />
              Mới
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: 'var(--ez-chart-navy)' }} />
              Lại
            </span>
          </div>
        </div>
        {data.length > 0 ? (
          <ResponsiveContainer width="100%" height={245}>
            <BarChart
              data={data}
              margin={{ top: 5, right: 6, left: -14, bottom: 0 }}
              barSize={8}
              onClick={handleChartClick}
              style={{ cursor: onSelectDate ? 'pointer' : 'default' }}
            >
              <XAxis dataKey="date" tickFormatter={formatAxisDate} stroke="var(--ez-chart-axis)" fontSize={10} tickLine={false} axisLine={false} />
              <YAxis allowDecimals={false} stroke="var(--ez-chart-axis)" fontSize={10} tickLine={false} axisLine={false} />
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--ez-chart-grid)" />
              <Tooltip
                content={<CustomTooltip selectedDate={selectedDate} clickable={!!onSelectDate} />}
                cursor={{ fill: 'var(--ez-brand-tint)', opacity: 0.45 }}
              />
              <Bar name="Lead Mới" dataKey="new_leads" fill="#1E5BD6" radius={[3, 3, 0, 0]} animationDuration={250}>
                {data.map((entry) => (
                  <Cell
                    key={`bar-new-${entry.date}`}
                    fill="#1E5BD6"
                    fillOpacity={!selectedDate || entry.date === selectedDate ? 1 : 0.25}
                  />
                ))}
              </Bar>
              <Bar name="Contact Lại" dataKey="recontact_leads" fill="var(--ez-chart-navy)" radius={[3, 3, 0, 0]} animationDuration={250}>
                {data.map((entry) => (
                  <Cell
                    key={`bar-re-${entry.date}`}
                    fill="var(--ez-chart-navy)"
                    fillOpacity={!selectedDate || entry.date === selectedDate ? 1 : 0.25}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-[245px] text-slate-400 text-xs">
            Chưa có dữ liệu so sánh
          </div>
        )}
      </div>
    </div>
  );
});
