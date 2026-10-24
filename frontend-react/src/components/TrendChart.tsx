import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import type { TrendData } from '../services/api';

interface TrendChartProps {
  data: TrendData[];
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-white/95 backdrop-blur-md border border-slate-200/90 rounded-xl shadow-card-hover p-3 text-xs">
        <p className="font-mono font-semibold text-navy mb-2 pb-1.5 border-b border-slate-100">{label}</p>
        <div className="space-y-1.5">
          {payload.map((p: any) => (
            <div key={p.name} className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-1.5 text-slate-500">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                {p.name}
              </span>
              <span className="font-mono font-semibold text-navy tabular-nums">{p.value}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return null;
};

export function TrendChart({ data }: TrendChartProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {/* Area Chart - chiếm 2/3 */}
      <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200/80 p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-5">
          <div>
            <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">Xu hướng Lead theo thời gian</h3>
            <p className="text-xs text-slate-500 mt-0.5">Biến động Lead Mới, Contact Lại & SĐT thu được</p>
          </div>
          <div className="flex items-center gap-3.5 text-[11px] font-medium text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-eztech inline-block" />
              Lead Mới
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-navy inline-block" />
              Contact Lại
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-gold inline-block" />
              SĐT thu được
            </span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={245}>
          <AreaChart data={data} margin={{ top: 5, right: 5, left: -24, bottom: 0 }}>
            <defs>
              <linearGradient id="colorNew" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#1E5BD6" stopOpacity={0.16}/>
                <stop offset="95%" stopColor="#1E5BD6" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorContact" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#0A1F44" stopOpacity={0.10}/>
                <stop offset="95%" stopColor="#0A1F44" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorPhone" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#F5B400" stopOpacity={0.18}/>
                <stop offset="95%" stopColor="#F5B400" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <XAxis dataKey="date" stroke="#94A3B8" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#94A3B8" fontSize={11} tickLine={false} axisLine={false} />
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" name="Lead Mới" dataKey="new_leads" stroke="#1E5BD6" strokeWidth={2} fillOpacity={1} fill="url(#colorNew)" dot={false} />
            <Area type="monotone" name="Lead Contact Lại" dataKey="recontact_leads" stroke="#0A1F44" strokeWidth={1.75} fillOpacity={1} fill="url(#colorContact)" dot={false} />
            <Area type="monotone" name="SĐT thu được" dataKey="phone_leads" stroke="#F5B400" strokeWidth={2} fillOpacity={1} fill="url(#colorPhone)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Bar Chart - chiếm 1/3 */}
      <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card">
        <div className="mb-5">
          <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">So sánh theo ngày</h3>
          <p className="text-xs text-slate-500 mt-0.5">Lead Mới vs Contact Lại</p>
        </div>
        <ResponsiveContainer width="100%" height={245}>
          <BarChart data={data} margin={{ top: 5, right: 5, left: -24, bottom: 0 }} barSize={8}>
            <XAxis dataKey="date" stroke="#94A3B8" fontSize={10} tickLine={false} axisLine={false} />
            <YAxis stroke="#94A3B8" fontSize={10} tickLine={false} axisLine={false} />
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
            <Tooltip content={<CustomTooltip />} />
            <Bar name="Lead Mới" dataKey="new_leads" fill="#1E5BD6" radius={[3, 3, 0, 0]} />
            <Bar name="Contact Lại" dataKey="recontact_leads" fill="#0A1F44" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
