
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface RatioChartProps {
  newLeads: number;
  contactedLeads: number;
  phoneLeads: number;
}

const COLORS = ['#1E5BD6', '#10B981', '#F59E0B'];

const CustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }: any) => {
  if (percent < 0.05) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={12} fontWeight={600}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
};

export function RatioChart({ newLeads, contactedLeads, phoneLeads }: RatioChartProps) {
  const data = [
    { name: 'Lead Mới', value: newLeads },
    { name: 'Liên Hệ', value: contactedLeads },
    { name: 'Có SĐT', value: phoneLeads },
  ].filter(d => d.value > 0);

  const contactRate = newLeads > 0 ? ((contactedLeads / newLeads) * 100).toFixed(1) : '0';
  const phoneRate = newLeads > 0 ? ((phoneLeads / newLeads) * 100).toFixed(1) : '0';

  return (
    <div className="bg-white rounded-2xl border border-[#E5E7EB] p-6 shadow-sm">
      <div className="mb-4">
        <h3 className="text-base font-semibold text-navy">Tỉ lệ chuyển đổi</h3>
        <p className="text-xs text-[#4B5563] mt-0.5">Phân bổ Lead trong kỳ</p>
      </div>

      {data.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={3}
                dataKey="value"
                labelLine={false}
                label={<CustomLabel />}
              >
                {data.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => [value, '']} />
            </PieChart>
          </ResponsiveContainer>

          <div className="mt-4 space-y-2.5">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-[#4B5563]">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block" />
                Tỉ lệ Contact
              </span>
              <span className="font-bold text-[#10B981]">{contactRate}%</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-[#4B5563]">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500 inline-block" />
                Tỉ lệ Có SĐT
              </span>
              <span className="font-bold text-[#F59E0B]">{phoneRate}%</span>
            </div>
            <div className="h-px bg-gray-100 my-2" />
            <div className="flex items-center justify-between text-sm">
              <span className="text-[#4B5563]">Tổng Lead</span>
              <span className="font-bold text-gray-800">{newLeads.toLocaleString()}</span>
            </div>
          </div>
        </>
      ) : (
        <div className="flex items-center justify-center h-[200px] text-gray-300 text-sm">
          Không có dữ liệu
        </div>
      )}
    </div>
  );
}
