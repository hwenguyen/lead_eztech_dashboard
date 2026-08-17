import React from 'react';
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
              <th className="px-6 py-4 font-medium">Customer ID</th>
              <th className="px-6 py-4 font-medium">Khách Hàng</th>
              <th className="px-6 py-4 font-medium">SĐT</th>
              <th className="px-6 py-4 font-medium">Ngày Tạo</th>
              <th className="px-6 py-4 font-medium">Trạng Thái</th>
              <th className="px-6 py-4 font-medium">Liên Hệ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {leads.length > 0 ? leads.map((lead) => (
              <tr key={lead.id} className="hover:bg-muted/30 transition-colors">
                <td className="px-6 py-4 font-medium text-foreground">{lead.customer_id}</td>
                <td className="px-6 py-4">{lead.name || '-'}</td>
                <td className="px-6 py-4">{lead.phone_number || '-'}</td>
                <td className="px-6 py-4 text-muted-foreground">
                  {format(new Date(lead.first_created_at), 'dd/MM/yyyy HH:mm')}
                </td>
                <td className="px-6 py-4">
                  {lead.status_tag ? (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                      {lead.status_tag}
                    </span>
                  ) : '-'}
                </td>
                <td className="px-6 py-4">
                  {lead.is_contacted ? (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                      Có
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                      Chưa
                    </span>
                  )}
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center text-muted-foreground">
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
