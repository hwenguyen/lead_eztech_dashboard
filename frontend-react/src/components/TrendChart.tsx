
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
      <div className="bg-white border border-[#E5E7EB] rounded-xl shadow-lg p-3 text-sm">
        <p className="font-semibold text-gray-700 mb-2">{label}</p>
        {payload.map((p: any) => (
          <div key={p.name} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: p.color }} />
            <span className="text-[#4B5563]">{p.name}:</span>
            <span className="font-semibold text-navy">{p.value}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

export function TrendChart({ data }: TrendChartProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Area Chart - chiếm 2/3 */}
      <div className="lg:col-span-2 bg-white rounded-2xl border border-[#E5E7EB] p-6 shadow-sm">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-base font-semibold text-navy">Xu hướng Lead theo thời gian</h3>
            <p className="text-xs text-[#4B5563] mt-0.5">Biến động Lead Mới, Liên Hệ, Có SĐT</p>
          </div>
          <div className="flex items-center gap-4 text-xs text-[#4B5563]">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-blue-500 inline-block" />Lead Mới</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-emerald-500 inline-block" />Liên Hệ</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-amber-500 inline-block" />Có SĐT</span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="colorNew" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#1E5BD6" stopOpacity={0.15}/>
                <stop offset="95%" stopColor="#1E5BD6" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorContact" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.15}/>
                <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorPhone" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.15}/>
                <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <XAxis dataKey="date" stroke="#d1d5db" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#d1d5db" fontSize={11} tickLine={false} axisLine={false} />
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" name="Lead Mới" dataKey="new_leads" stroke="#1E5BD6" strokeWidth={2} fillOpacity={1} fill="url(#colorNew)" dot={false} />
            <Area type="monotone" name="Lead Liên Hệ" dataKey="contacted_leads" stroke="#10b981" strokeWidth={2} fillOpacity={1} fill="url(#colorContact)" dot={false} />
            <Area type="monotone" name="Lead Có SĐT" dataKey="phone_leads" stroke="#f59e0b" strokeWidth={2} fillOpacity={1} fill="url(#colorPhone)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Bar Chart - chiếm 1/3 */}
      <div className="bg-white rounded-2xl border border-[#E5E7EB] p-6 shadow-sm">
        <div className="mb-6">
          <h3 className="text-base font-semibold text-navy">So sánh theo ngày</h3>
          <p className="text-xs text-[#4B5563] mt-0.5">Tổng Lead Mới vs Liên Hệ</p>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }} barSize={10}>
            <XAxis dataKey="date" stroke="#d1d5db" fontSize={10} tickLine={false} axisLine={false} />
            <YAxis stroke="#d1d5db" fontSize={10} tickLine={false} axisLine={false} />
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
            <Tooltip content={<CustomTooltip />} />
            <Bar name="Lead Mới" dataKey="new_leads" fill="#1E5BD6" radius={[4,4,0,0]} />
            <Bar name="Liên Hệ" dataKey="contacted_leads" fill="#10b981" radius={[4,4,0,0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
