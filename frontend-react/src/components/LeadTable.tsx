
import type { Lead } from '../services/api';
import { format } from 'date-fns';

interface LeadTableProps {
  leads: Lead[];
}

export function LeadTable({ leads }: LeadTableProps) {
  return (
    <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
      <div className="p-6 border-b border-border">
        <h3 className="text-lg font-medium text-foreground">Danh sách Lead mới nhất</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-xs text-muted-foreground bg-muted/50 uppercase">
            <tr>
              <th className="px-6 py-4 font-medium min-w-[150px]">Khách Hàng</th>
              <th className="px-6 py-4 font-medium min-w-[150px]">Nhân Viên Phụ Trách</th>
              <th className="px-6 py-4 font-medium min-w-[120px]">SĐT</th>
              <th className="px-6 py-4 font-medium w-full">Tin Nhắn</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {leads.length > 0 ? leads.map((lead) => (
              <tr key={lead.id} className="hover:bg-muted/30 transition-colors">
                <td className="px-6 py-4 font-medium text-foreground">
                  {lead.name || 'Khách từ CRM'}
                  <div className="text-xs text-muted-foreground mt-1 font-normal">
                    {format(new Date(lead.first_created_at), 'dd/MM HH:mm')}
                  </div>
                </td>
                <td className="px-6 py-4">
                  {lead.assigned_users ? (
                    <div className="flex flex-wrap gap-1">
                      {lead.assigned_users.split(',').map((u, i) => (
                        <span key={i} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                          {u.trim()}
                        </span>
                      ))}
                    </div>
                  ) : '-'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">{lead.phone_number || '-'}</td>
                <td className="px-6 py-4">
                  <div className="max-h-[120px] overflow-y-auto pr-2 text-sm text-foreground/90 whitespace-pre-wrap rounded bg-muted/20 p-2 border border-border/50">
                    {lead.messages || <span className="text-muted-foreground italic">Không có tin nhắn</span>}
                  </div>
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={4} className="px-6 py-12 text-center text-muted-foreground">
                  Không có dữ liệu
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
