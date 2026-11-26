import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { BulletinCalendarBlock } from './BulletinCalendarBlock';
import {
  Bell,
  BellRing,
  Check,
  CheckSquare,
  Square,
  Clock,
  Calendar,
  Plus,
  Trash2,
  RefreshCw,
  Pin,
  Search,
  Send,
  Users,
  Settings,
  ExternalLink,
  Repeat,
  AlertCircle,
  Eye,
  Newspaper,
  ListTodo,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Pencil,
  CornerDownRight,
  ThumbsUp,
  Globe,
  FileText,
  StickyNote,
  X,
} from 'lucide-react';
import {
  fetchBulletinPosts,
  fetchBulletinPostReaders,
  markBulletinPostRead,
  markAllBulletinPostsRead,
  unmarkBulletinPostRead,
  togglePinBulletinPost,
  syncBulletinPosts,
  aiExtractBulletinPost,
  fetchWorkReminders,
  createWorkReminder,
  updateWorkReminder,
  deleteWorkReminder,
  fetchDailyChecklists,
  fetchPendingRolloverItems,
  rolloverPendingChecklistItems,
  createDailyChecklist,
  updateDailyChecklist,
  deleteDailyChecklist,
  addChecklistTaskItem,
  updateChecklistTaskItem,
  deleteChecklistTaskItem,
  fetchAdminBulletinStaff,
  updateAdminBulletinStaff,
  syncConsultantZaloContacts,
  testStaffZaloMessage,
  fetchBulletinConfig,
  updateBulletinConfig,
  dispatchBulletinReminders,
  fetchBulletinZaloLogs,
  getStoredAuth,
  isAbortError,
  type BulletinPostItem,
  type BulletinReaderInfo,
  type BulletinAiExtractResponse,
  type WorkReminderItem,
  type DailyChecklistItemGroup,
  type PendingRolloverItem,
  type StaffZaloMapping,
  type ConsultantZaloContact,
  type ZaloReminderLogItem,
} from '../services/api';
import { getEffectivePermissions } from '../config/permissions';
import { getVnTodayStr } from '../utils/format';
import { showAppToast } from '../utils/toast';
import { AccessibleModal } from './AccessibleModal';
import { ErrorBanner } from './ErrorBanner';

interface BulletinDashboardProps {
  onUnreadCountChange?: (count: number) => void;
}

const BOSS_FILTERS: { key: string; label: string }[] = [
  { key: 'all', label: 'Tất cả sếp' },
  { key: 'ann', label: 'Ann' },
  { key: 'tuan_anh', label: 'TRẦN HÀ TUẤN ANH' },
  { key: 'hien_minh', label: 'Hiền Minhh' },
];

const BOSS_BADGE_MAP: Record<string, string> = {
  ann: 'bg-rose-50 text-rose-700 border-rose-200',
  tuan_anh: 'bg-blue-50 text-blue-700 border-blue-200',
  hien_minh: 'bg-amber-50 text-amber-800 border-amber-200',
};

const BOSS_AVATAR_MAP: Record<string, { initials: string; bg: string; ring: string; shortLabel: string }> = {
  ann: {
    initials: 'AN',
    bg: 'bg-gradient-to-br from-rose-500 to-rose-600 text-white',
    ring: 'ring-rose-400',
    shortLabel: 'Ann',
  },
  tuan_anh: {
    initials: 'TA',
    bg: 'bg-gradient-to-br from-brand-500 to-navy text-white',
    ring: 'ring-brand-500',
    shortLabel: 'Tuấn Anh',
  },
  hien_minh: {
    initials: 'HM',
    bg: 'bg-gradient-to-br from-amber-500 to-gold-600 text-white',
    ring: 'ring-gold-500',
    shortLabel: 'Hiền Minhh',
  },
};

function getInitials(name?: string | null): string {
  if (!name) return 'EZ';
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

const PRIORITY_BADGE_MAP: Record<string, { label: string; cls: string }> = {
  low: { label: 'Thấp', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
  normal: { label: 'Bình thường', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  high: { label: 'Cao', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  urgent: { label: 'Khẩn cấp', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
};

const RECURRENCE_LABELS: Record<string, string> = {
  none: 'Không lặp',
  daily: 'Lặp hàng ngày',
  weekly: 'Lặp hàng tuần',
  monthly: 'Lặp hàng tháng',
};

const WEEKDAY_OPTIONS: { day: number; label: string }[] = [
  { day: 0, label: 'T2' },
  { day: 1, label: 'T3' },
  { day: 2, label: 'T4' },
  { day: 3, label: 'T5' },
  { day: 4, label: 'T6' },
  { day: 5, label: 'T7' },
  { day: 6, label: 'CN' },
];

function getDefaultRemindAt(minutesAhead = 60): string {
  const now = new Date(Date.now() + 7 * 3600 * 1000 + minutesAhead * 60 * 1000);
  return now.toISOString().slice(0, 16);
}

function getTodayPresetTime(hourStr: string, addDays = 0): string {
  const day = getVnTodayStr(addDays);
  return `${day}T${hourStr}`;
}

export function BulletinDashboard({ onUnreadCountChange }: BulletinDashboardProps) {
  const currentUser = useMemo(() => getStoredAuth().user, []);
  const perms = useMemo(() => getEffectivePermissions(currentUser), [currentUser]);
  const isAdmin = perms.isAdmin;

  // Bulletin state
  const [posts, setPosts] = useState<BulletinPostItem[]>([]);
  const [postsTotal, setPostsTotal] = useState(0);
  const [totalAllPosts, setTotalAllPosts] = useState(0);
  const [unreadCount, setUnreadCount] = useState(0);
  const [bossCounts, setBossCounts] = useState<Record<string, number>>({});
  const [bossFilter, setBossFilter] = useState('all');
  const [readFilter, setReadFilter] = useState<'all' | 'unread' | 'read'>('all');
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [postsPage, setPostsPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [syncingPosts, setSyncingPosts] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [expandedPostIds, setExpandedPostIds] = useState<Record<number, boolean>>({});
  const [openReadersPostId, setOpenReadersPostId] = useState<number | null>(null);
  const [postReadersMap, setPostReadersMap] = useState<Record<number, BulletinReaderInfo[]>>({});
  const [loadingReadersPostId, setLoadingReadersPostId] = useState<number | null>(null);

  const postsAbortRef = useRef<AbortController | null>(null);
  const feedSectionRef = useRef<HTMLElement | null>(null);
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const adminStaffLoadedRef = useRef(false);
  const POSTS_PAGE_SIZE = 10;

  // Right panel sub-tabs
  const [workTab, setWorkTab] = useState<'checklist' | 'reminders' | 'admin'>('checklist');
  const [calendarRefreshTick, setCalendarRefreshTick] = useState(0);
  const [pendingRemindersCount, setPendingRemindersCount] = useState(0);
  const [markingAllRead, setMarkingAllRead] = useState(false);

  // Checklist state
  const [checklistDate, setChecklistDate] = useState(() => getVnTodayStr(0));
  const [checklists, setChecklists] = useState<DailyChecklistItemGroup[]>([]);
  const [checklistSummary, setChecklistSummary] = useState({ total_items: 0, done_items: 0, pending_items: 0 });
  const [loadingChecklists, setLoadingChecklists] = useState(false);
  const [inlineItemInputs, setInlineItemInputs] = useState<Record<number, string>>({});
  const [editingItemId, setEditingItemId] = useState<number | null>(null);
  const [editingItemText, setEditingItemText] = useState('');

  // A3: Rollover unfinished items from previous days
  const [rolloverItems, setRolloverItems] = useState<PendingRolloverItem[]>([]);
  const [rollingOver, setRollingOver] = useState(false);

  // Reminder state
  const [reminders, setReminders] = useState<WorkReminderItem[]>([]);
  const [reminderStatusFilter, setReminderStatusFilter] = useState<'pending' | 'completed' | 'all'>('pending');
  const [loadingReminders, setLoadingReminders] = useState(false);

  // Admin state
  const [adminOwnerFilter, setAdminOwnerFilter] = useState<string>('');
  const [staffList, setStaffList] = useState<StaffZaloMapping[]>([]);
  const [zaloContacts, setZaloContacts] = useState<ConsultantZaloContact[]>([]);
  const [zaloLogs, setZaloLogs] = useState<ZaloReminderLogItem[]>([]);
  const [sourceConfig, setSourceConfig] = useState<Record<string, any> | null>(null);
  const [scanningContacts, setScanningContacts] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchPreview, setDispatchPreview] = useState<any>(null);

  // Reminder Modal (Create & Edit)
  const [reminderModalOpen, setReminderModalOpen] = useState(false);
  const [editingReminderId, setEditingReminderId] = useState<number | null>(null);
  const [remSourcePost, setRemSourcePost] = useState<BulletinPostItem | null>(null);
  const [remTitle, setRemTitle] = useState('');
  const [remDesc, setRemDesc] = useState('');
  const [remAt, setRemAt] = useState(() => getDefaultRemindAt(60));
  const [remPriority, setRemPriority] = useState<'low' | 'normal' | 'high' | 'urgent'>('normal');
  const [remRecurrence, setRemRecurrence] = useState<'none' | 'daily' | 'weekly' | 'monthly'>('none');
  const [remOwnerIds, setRemOwnerIds] = useState<number[]>([]);
  const [remNotify11h, setRemNotify11h] = useState(true);
  const [remNotify15h, setRemNotify15h] = useState(true);
  const [remNotifyExact, setRemNotifyExact] = useState(true);
  const [savingRem, setSavingRem] = useState(false);

  // Create Checklist Modal (supports Admin multi-assign)
  const [checklistModalOpen, setChecklistModalOpen] = useState(false);
  const [clSourcePost, setClSourcePost] = useState<BulletinPostItem | null>(null);
  const [clTitle, setClTitle] = useState('');
  const [clDateInput, setClDateInput] = useState(() => getVnTodayStr(0));
  const [clItemsText, setClItemsText] = useState('');
  const [clRecurring, setClRecurring] = useState(false);
  const [clOwnerIds, setClOwnerIds] = useState<number[]>([]);
  const [clAdminNote, setClAdminNote] = useState('');
  const [savingCl, setSavingCl] = useState(false);

  // Admin inline Note cho nhân viên trên từng checklist
  const [editingNoteChecklistId, setEditingNoteChecklistId] = useState<number | null>(null);
  const [editingNoteText, setEditingNoteText] = useState('');
  const [savingChecklistNote, setSavingChecklistNote] = useState(false);

  // A2: AI Extract Modal
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [aiLoadingPostId, setAiLoadingPostId] = useState<number | null>(null);
  const [aiSourcePost, setAiSourcePost] = useState<BulletinPostItem | null>(null);
  const [aiResult, setAiResult] = useState<BulletinAiExtractResponse | null>(null);
  const [aiClTitle, setAiClTitle] = useState('');
  const [aiClItemsText, setAiClItemsText] = useState('');
  const [aiIncludeReminder, setAiIncludeReminder] = useState(false);
  const [aiRemTitle, setAiRemTitle] = useState('');
  const [aiRemAt, setAiRemAt] = useState(() => getDefaultRemindAt(60));
  const [aiRemPriority, setAiRemPriority] = useState<'low' | 'normal' | 'high' | 'urgent'>('normal');
  const [aiOwnerIds, setAiOwnerIds] = useState<number[]>([]);
  const [savingAi, setSavingAi] = useState(false);

  // Fix #6: Debounce search 350ms (chỉ chạy khi giá trị tìm kiếm thực sự thay đổi, tránh double-fetch khi mới mở trang)
  useEffect(() => {
    const trimmed = searchInput.trim();
    if (trimmed === debouncedSearch) return;
    const timer = window.setTimeout(() => {
      setDebouncedSearch(trimmed);
      setPostsPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [searchInput, debouncedSearch]);

  const loadPosts = useCallback(async (targetPage = postsPage) => {
    postsAbortRef.current?.abort();
    const controller = new AbortController();
    postsAbortRef.current = controller;

    setLoadingPosts(true);
    setErrorMsg(null);
    try {
      const data = await fetchBulletinPosts(
        {
          boss_key: bossFilter,
          read_status: readFilter,
          search: debouncedSearch || undefined,
          page: targetPage,
          size: POSTS_PAGE_SIZE,
        },
        { signal: controller.signal }
      );
      if (controller.signal.aborted) return;
      setPosts(data.items || []);
      setPostsTotal(data.total || 0);
      setTotalAllPosts(data.summary?.total_all ?? data.total ?? 0);
      setTotalPages(data.total_pages || 1);
      setUnreadCount(data.summary?.unread_count ?? 0);
      setBossCounts(data.summary?.boss_counts || {});
      onUnreadCountChange?.(data.summary?.unread_count ?? 0);
    } catch (err: any) {
      if (isAbortError(err) || controller.signal.aborted) return;
      setErrorMsg(err?.response?.data?.detail || 'Không thể tải danh sách bản tin.');
    } finally {
      if (postsAbortRef.current === controller) {
        setLoadingPosts(false);
      }
    }
  }, [bossFilter, readFilter, debouncedSearch, postsPage, onUnreadCountChange]);

  const handleChangePostsPage = useCallback((nextPage: number) => {
    setPostsPage((prev) => {
      const clamped = Math.max(1, Math.min(totalPages, nextPage));
      if (clamped !== prev) {
        setOpenReadersPostId(null);
        window.requestAnimationFrame(() => {
          feedSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
      return clamped;
    });
  }, [totalPages]);

  const handleToggleReaders = async (postId: number) => {
    if (openReadersPostId === postId) {
      setOpenReadersPostId(null);
      return;
    }
    setOpenReadersPostId(postId);
    if (!isAdmin || postReadersMap[postId]) return;
    setLoadingReadersPostId(postId);
    try {
      const res = await fetchBulletinPostReaders(postId);
      setPostReadersMap((prev) => ({ ...prev, [postId]: res.items || [] }));
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể tải danh sách người đã đọc', 'error');
    } finally {
      setLoadingReadersPostId(null);
    }
  };

  const ensureStaffListLoaded = useCallback(async () => {
    if (!isAdmin || adminStaffLoadedRef.current) return;
    try {
      const staffRes = await fetchAdminBulletinStaff();
      adminStaffLoadedRef.current = true;
      setStaffList(staffRes.items || []);
    } catch {
      // ignore lazy staff load error
    }
  }, [isAdmin]);

  const loadChecklists = useCallback(async () => {
    setLoadingChecklists(true);
    try {
      const data = await fetchDailyChecklists({
        checklist_date: checklistDate,
        owner_user_id: isAdmin && adminOwnerFilter ? Number(adminOwnerFilter) : undefined,
      });
      setChecklists(data.items || []);
      setChecklistSummary(data.summary || { total_items: 0, done_items: 0, pending_items: 0 });
      if (typeof data.pending_reminders_count === 'number') {
        setPendingRemindersCount(data.pending_reminders_count);
      }
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi tải checklist hàng ngày', 'error');
    } finally {
      setLoadingChecklists(false);
    }
  }, [checklistDate, isAdmin, adminOwnerFilter]);

  const loadRollover = useCallback(async () => {
    const today = getVnTodayStr(0);
    if (checklistDate !== today) {
      setRolloverItems([]);
      return;
    }
    try {
      const res = await fetchPendingRolloverItems(today);
      setRolloverItems(res.items || []);
    } catch {
      setRolloverItems([]);
    }
  }, [checklistDate]);

  const loadReminders = useCallback(async () => {
    setLoadingReminders(true);
    try {
      const data = await fetchWorkReminders({
        status: reminderStatusFilter,
        owner_user_id: isAdmin && adminOwnerFilter ? Number(adminOwnerFilter) : undefined,
      });
      const items = data.items || [];
      setReminders(items);
      if (reminderStatusFilter === 'pending' || reminderStatusFilter === 'all') {
        setPendingRemindersCount(items.filter((r) => r.status === 'pending').length);
      }
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi tải danh sách nhắc hẹn', 'error');
    } finally {
      setLoadingReminders(false);
    }
  }, [reminderStatusFilter, isAdmin, adminOwnerFilter]);

  const loadAdminStaffAndLogs = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const [staffRes, logsRes, cfgRes] = await Promise.all([
        fetchAdminBulletinStaff(),
        fetchBulletinZaloLogs(40),
        fetchBulletinConfig(),
      ]);
      adminStaffLoadedRef.current = true;
      setStaffList(staffRes.items || []);
      setZaloLogs(logsRes.items || []);
      setSourceConfig(cfgRes || null);
    } catch {
      // ignore initial admin fetch warning
    }
  }, [isAdmin]);

  // Chỉ tải trang hiện tại của Bảng Tin (hủy request cũ khi bấm sang trang)
  useEffect(() => {
    loadPosts(postsPage);
    return () => {
      postsAbortRef.current?.abort();
    };
  }, [loadPosts, postsPage]);

  // Lazy-load đúng tab công việc đang mở (mặc định chỉ load Checklist khi mới vào; sang tab Nhắc hẹn / Quản trị mới load phần đó)
  useEffect(() => {
    if (workTab === 'checklist') {
      loadChecklists();
      loadRollover();
    }
  }, [workTab, loadChecklists, loadRollover]);

  useEffect(() => {
    if (workTab === 'reminders') {
      loadReminders();
    }
  }, [workTab, loadReminders]);

  useEffect(() => {
    if (workTab === 'admin') {
      loadAdminStaffAndLogs();
    }
  }, [workTab, loadAdminStaffAndLogs]);

  const handleSyncGroup = async () => {
    setSyncingPosts(true);
    try {
      const res = await syncBulletinPosts(isAdmin);
      if (res.success) {
        showAppToast(res.message, 'success');
        await loadPosts(1);
        setPostsPage(1);
      } else {
        showAppToast(res.message || 'Đồng bộ bản tin chưa thành công', 'warning');
      }
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi đồng bộ bản tin từ Zalo', 'error');
    } finally {
      setSyncingPosts(false);
    }
  };

  const handleMarkAllRead = async () => {
    if (unreadCount <= 0 || markingAllRead) return;
    const scopeLabel = bossFilter === 'all' ? 'toàn bộ bảng tin' : 'tất cả bài viết của sếp đang lọc';
    if (!window.confirm(`Đánh dấu đã đọc ${scopeLabel}?`)) return;
    setMarkingAllRead(true);
    try {
      const res = await markAllBulletinPostsRead(bossFilter);
      showAppToast(`Đã đánh dấu đã đọc ${res.marked_count} bài viết`, 'success');
      await loadPosts(1);
      setPostsPage(1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể đánh dấu tất cả đã đọc', 'error');
    } finally {
      setMarkingAllRead(false);
    }
  };

  const handleToggleRead = async (post: BulletinPostItem) => {
    try {
      if (post.is_read) {
        await unmarkBulletinPostRead(post.id);
        setPosts((prev) =>
          prev.map((p) =>
            p.id === post.id ? { ...p, is_read: false, read_at: null, read_count: Math.max(0, p.read_count - 1) } : p
          )
        );
        const nextUnread = unreadCount + 1;
        setUnreadCount(nextUnread);
        onUnreadCountChange?.(nextUnread);
      } else {
        await markBulletinPostRead(post.id);
        setPosts((prev) =>
          prev.map((p) => (p.id === post.id ? { ...p, is_read: true, read_count: p.read_count + 1 } : p))
        );
        const nextUnread = Math.max(0, unreadCount - 1);
        setUnreadCount(nextUnread);
        onUnreadCountChange?.(nextUnread);
        showAppToast('Đã đánh dấu bản tin là đã đọc', 'success');
      }
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể cập nhật trạng thái đọc', 'error');
    }
  };

  const handleTogglePin = async (post: BulletinPostItem) => {
    try {
      const res = await togglePinBulletinPost(post.id);
      setPosts((prev) => prev.map((p) => (p.id === post.id ? { ...p, is_pinned: res.is_pinned } : p)));
      showAppToast(res.is_pinned ? 'Đã ghim bản tin lên đầu' : 'Đã bỏ ghim bản tin', 'info');
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể ghim bản tin', 'error');
    }
  };

  // A2: AI Tách việc từ bản tin
  const handleAiExtract = async (post: BulletinPostItem) => {
    ensureStaffListLoaded();
    setAiLoadingPostId(post.id);
    try {
      const res = await aiExtractBulletinPost(post.id);
      setAiSourcePost(post);
      setAiResult(res);
      setAiClTitle(res.checklist_title || `Việc từ ${post.boss_display_name}`);
      setAiClItemsText((res.checklist_items || []).join('\n'));
      if (res.suggested_reminder) {
        setAiIncludeReminder(true);
        setAiRemTitle(res.suggested_reminder.title);
        setAiRemAt(res.suggested_reminder.remind_at || getDefaultRemindAt(60));
        setAiRemPriority(res.suggested_reminder.priority || 'normal');
      } else {
        setAiIncludeReminder(false);
        setAiRemTitle(`Nhắc: ${post.title || post.boss_display_name}`);
        setAiRemAt(getDefaultRemindAt(60));
        setAiRemPriority('normal');
      }
      setAiOwnerIds(isAdmin && adminOwnerFilter ? [Number(adminOwnerFilter)] : []);
      setAiModalOpen(true);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể tách việc bằng AI lúc này', 'error');
    } finally {
      setAiLoadingPostId(null);
    }
  };

  const handleSaveAiExtracted = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!aiSourcePost) return;
    const items = aiClItemsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    if (items.length === 0 && !aiIncludeReminder) {
      showAppToast('Vui lòng nhập ít nhất 1 đầu việc hoặc bật nhắc hẹn', 'warning');
      return;
    }
    setSavingAi(true);
    try {
      const today = getVnTodayStr(0);
      const ownerPayload = isAdmin && aiOwnerIds.length > 0 ? { owner_user_ids: aiOwnerIds } : {};
      const tasks: Promise<any>[] = [];
      if (items.length > 0) {
        tasks.push(
          createDailyChecklist({
            title: aiClTitle.trim() || `Việc từ ${aiSourcePost.boss_display_name}`,
            checklist_date: today,
            items,
            source_post_id: aiSourcePost.id,
            ...ownerPayload,
          })
        );
      }
      if (aiIncludeReminder && aiRemTitle.trim() && aiRemAt) {
        tasks.push(
          createWorkReminder({
            title: aiRemTitle.trim(),
            description: aiResult?.summary || undefined,
            remind_at: aiRemAt,
            priority: aiRemPriority,
            source_post_id: aiSourcePost.id,
            notify_11h: true,
            notify_15h: true,
            notify_exact_time: true,
            ...ownerPayload,
          })
        );
      }
      await Promise.all(tasks);
      showAppToast('Đã lưu checklist / nhắc hẹn từ AI tách việc!', 'success');
      setAiModalOpen(false);
      setChecklistDate(today);
      await Promise.all([loadChecklists(), loadReminders(), loadPosts(postsPage)]);
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi khi lưu kết quả AI', 'error');
    } finally {
      setSavingAi(false);
    }
  };

  // A3: Rollover
  const handleRolloverPending = async () => {
    setRollingOver(true);
    try {
      const res = await rolloverPendingChecklistItems({ target_date: checklistDate });
      showAppToast(res.message || 'Đã chuyển tiếp việc chưa xong sang hôm nay', 'success');
      await Promise.all([loadChecklists(), loadRollover()]);
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể chuyển tiếp đầu việc', 'error');
    } finally {
      setRollingOver(false);
    }
  };

  // Reminder Modal open (Create or Edit)
  const openReminderModal = (
    post?: BulletinPostItem | null,
    existingRem?: WorkReminderItem | null,
    defaultDateStr?: string
  ) => {
    ensureStaffListLoaded();
    if (existingRem) {
      setEditingReminderId(existingRem.id);
      setRemSourcePost(null);
      setRemTitle(existingRem.title);
      setRemDesc(existingRem.description || '');
      setRemAt(existingRem.remind_at || getDefaultRemindAt(60));
      setRemPriority(existingRem.priority || 'normal');
      setRemRecurrence(existingRem.recurrence_rule || 'none');
      setRemOwnerIds([]);
      setRemNotify11h(existingRem.notify_11h);
      setRemNotify15h(existingRem.notify_15h);
      setRemNotifyExact(existingRem.notify_exact_time);
    } else {
      setEditingReminderId(null);
      setRemSourcePost(post || null);
      setRemTitle(post ? `Theo dõi: ${post.title || 'Bản tin sếp ' + post.boss_display_name}` : '');
      setRemDesc(post ? post.content.slice(0, 300) : '');
      setRemAt(defaultDateStr ? `${defaultDateStr}T09:00` : getDefaultRemindAt(60));
      setRemPriority('normal');
      setRemRecurrence('none');
      setRemOwnerIds(isAdmin && adminOwnerFilter ? [Number(adminOwnerFilter)] : []);
      setRemNotify11h(true);
      setRemNotify15h(true);
      setRemNotifyExact(true);
    }
    setReminderModalOpen(true);
  };

  const openChecklistModal = (post?: BulletinPostItem | null) => {
    ensureStaffListLoaded();
    setClSourcePost(post || null);
    setClTitle(post ? `Việc từ bản tin (${post.boss_display_name})` : 'Checklist công việc hôm nay');
    setClDateInput(checklistDate || getVnTodayStr(0));
    setClItemsText(post ? post.title || '' : '');
    setClRecurring(false);
    setClOwnerIds(isAdmin && adminOwnerFilter ? [Number(adminOwnerFilter)] : []);
    setClAdminNote('');
    setChecklistModalOpen(true);
  };

  const handleSaveReminder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!remTitle.trim() || !remAt) return;
    setSavingRem(true);
    try {
      if (editingReminderId) {
        await updateWorkReminder(editingReminderId, {
          title: remTitle.trim(),
          description: remDesc.trim(),
          remind_at: remAt,
          priority: remPriority,
          recurrence_rule: remRecurrence,
          notify_11h: remNotify11h,
          notify_15h: remNotify15h,
          notify_exact_time: remNotifyExact,
        });
        showAppToast('Đã cập nhật nhắc hẹn', 'success');
      } else {
        const res = await createWorkReminder({
          title: remTitle.trim(),
          description: remDesc.trim() || undefined,
          remind_at: remAt,
          priority: remPriority,
          recurrence_rule: remRecurrence,
          source_post_id: remSourcePost?.id || null,
          owner_user_ids: isAdmin && remOwnerIds.length > 0 ? remOwnerIds : null,
          notify_11h: remNotify11h,
          notify_15h: remNotify15h,
          notify_exact_time: remNotifyExact,
        });
        const cnt = res.created_count || 1;
        showAppToast(cnt > 1 ? `Đã tạo nhắc hẹn cho ${cnt} nhân sự` : 'Đã tạo nhắc hẹn thành công', 'success');
      }
      setReminderModalOpen(false);
      setWorkTab('reminders');
      setCalendarRefreshTick((t) => t + 1);
      await Promise.all([loadReminders(), remSourcePost ? loadPosts(postsPage) : Promise.resolve()]);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi khi lưu nhắc hẹn', 'error');
    } finally {
      setSavingRem(false);
    }
  };

  const handleSnoozeReminder = async (rem: WorkReminderItem, nextTime: string, label: string) => {
    try {
      await updateWorkReminder(rem.id, { remind_at: nextTime, status: 'pending' });
      showAppToast(`Đã hoãn nhắc hẹn sang ${label}`, 'info');
      await loadReminders();
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể hoãn nhắc hẹn', 'error');
    }
  };

  const handleToggleReminderStatus = async (rem: WorkReminderItem) => {
    const nextStatus = rem.status === 'completed' ? 'pending' : 'completed';
    try {
      const res = await updateWorkReminder(rem.id, { status: nextStatus });
      if (nextStatus === 'completed' && res.next_reminder) {
        showAppToast(`Đã xong! Tự động tạo kỳ tiếp theo lúc ${res.next_reminder.remind_at_display}`, 'success');
      } else {
        showAppToast(nextStatus === 'completed' ? 'Đã hoàn thành nhắc hẹn' : 'Đã mở lại nhắc hẹn', 'success');
      }
      await loadReminders();
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể cập nhật nhắc hẹn', 'error');
    }
  };

  const handleDeleteReminder = async (remId: number) => {
    try {
      await deleteWorkReminder(remId);
      const deletedRem = reminders.find((r) => r.id === remId);
      setReminders((prev) => prev.filter((r) => r.id !== remId));
      if (deletedRem?.status === 'pending') {
        setPendingRemindersCount((c) => Math.max(0, c - 1));
      }
      setCalendarRefreshTick((t) => t + 1);
      showAppToast('Đã xóa nhắc hẹn', 'info');
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể xóa nhắc hẹn', 'error');
    }
  };

  const handleSaveChecklist = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clTitle.trim()) return;
    const items = clItemsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    setSavingCl(true);
    try {
      const res = await createDailyChecklist({
        title: clTitle.trim(),
        checklist_date: clDateInput,
        items,
        source_post_id: clSourcePost?.id || null,
        owner_user_ids: isAdmin && clOwnerIds.length > 0 ? clOwnerIds : null,
        is_recurring_daily: clRecurring,
        admin_note: isAdmin && clAdminNote.trim() ? clAdminNote.trim() : null,
      });
      const cnt = res.created_count || 1;
      showAppToast(cnt > 1 ? `Đã phân checklist cho ${cnt} nhân sự` : 'Đã tạo checklist công việc', 'success');
      setChecklistModalOpen(false);
      setClAdminNote('');
      setChecklistDate(clDateInput);
      setWorkTab('checklist');
      await Promise.all([loadChecklists(), clSourcePost ? loadPosts(postsPage) : Promise.resolve()]);
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi khi tạo checklist', 'error');
    } finally {
      setSavingCl(false);
    }
  };

  const handleSaveChecklistAdminNote = async (checklistId: number) => {
    setSavingChecklistNote(true);
    try {
      const updated = await updateDailyChecklist(checklistId, { admin_note: editingNoteText.trim() });
      setChecklists((prev) =>
        prev.map((cl) =>
          cl.id === checklistId ? { ...cl, admin_note: updated.admin_note, admin_note_by: updated.admin_note_by } : cl
        )
      );
      setEditingNoteChecklistId(null);
      setEditingNoteText('');
      showAppToast(updated.admin_note ? 'Đã lưu ghi chú cho nhân viên' : 'Đã xóa ghi chú', 'success');
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể lưu ghi chú', 'error');
    } finally {
      setSavingChecklistNote(false);
    }
  };

  const handleToggleChecklistItem = async (checklistId: number, itemId: number, currentDone: boolean) => {
    setChecklists((prev) =>
      prev.map((cl) => {
        if (cl.id !== checklistId) return cl;
        const nextItems = cl.items.map((it) => (it.id === itemId ? { ...it, is_done: !currentDone } : it));
        const doneCount = nextItems.filter((it) => it.is_done).length;
        return {
          ...cl,
          items: nextItems,
          done_count: doneCount,
          progress_pct: nextItems.length ? Math.round((doneCount / nextItems.length) * 100) : 0,
        };
      })
    );
    try {
      await updateChecklistTaskItem(itemId, { is_done: !currentDone });
      await loadChecklists();
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể cập nhật hạng mục', 'error');
      await loadChecklists();
    }
  };

  const handleSaveEditChecklistItem = async (itemId: number) => {
    const clean = editingItemText.trim();
    if (!clean) {
      setEditingItemId(null);
      return;
    }
    try {
      await updateChecklistTaskItem(itemId, { content: clean });
      setEditingItemId(null);
      setEditingItemText('');
      await loadChecklists();
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể sửa đầu việc', 'error');
    }
  };

  const handleAddInlineItem = async (checklistId: number) => {
    const content = (inlineItemInputs[checklistId] || '').trim();
    if (!content) return;
    try {
      await addChecklistTaskItem(checklistId, content);
      setInlineItemInputs((prev) => ({ ...prev, [checklistId]: '' }));
      await loadChecklists();
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể thêm đầu việc', 'error');
    }
  };

  const handleDeleteChecklistItem = async (itemId: number) => {
    try {
      await deleteChecklistTaskItem(itemId);
      await loadChecklists();
      setCalendarRefreshTick((t) => t + 1);
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể xóa đầu việc', 'error');
    }
  };

  const handleDeleteChecklist = async (checklistId: number) => {
    try {
      await deleteDailyChecklist(checklistId);
      setChecklists((prev) => prev.filter((c) => c.id !== checklistId));
      setCalendarRefreshTick((t) => t + 1);
      showAppToast('Đã xóa checklist', 'info');
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể xóa checklist', 'error');
    }
  };

  // Admin handlers
  const handleScanZaloContacts = async () => {
    setScanningContacts(true);
    try {
      const res = await syncConsultantZaloContacts(true);
      setZaloContacts(res.contacts || []);
      showAppToast(res.message, 'success');
      await loadAdminStaffAndLogs();
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể quét hội thoại Zalo Eztech Consultant', 'error');
    } finally {
      setScanningContacts(false);
    }
  };

  const handleSaveStaffMapping = async (staff: StaffZaloMapping) => {
    try {
      await updateAdminBulletinStaff(staff.user_id, {
        full_name: staff.full_name,
        phone_number: staff.phone_number,
        zalo_conversation_id: staff.zalo_conversation_id,
        zalo_display_name: staff.zalo_display_name,
        receive_daily_digest: staff.receive_daily_digest,
        is_active: staff.is_active,
      });
      showAppToast(`Đã lưu cấu hình Zalo cho ${staff.full_name}`, 'success');
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi lưu cấu hình nhân sự', 'error');
    }
  };

  const handleTestStaffZalo = async (userId: number) => {
    try {
      const res = await testStaffZaloMessage(userId);
      showAppToast(res.message, res.success ? 'success' : 'error');
      await loadAdminStaffAndLogs();
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi gửi tin Zalo thử nghiệm', 'error');
    }
  };

  const handleDispatch = async (slot: '11h' | '15h' | 'exact', dryRun: boolean) => {
    setDispatching(true);
    setDispatchPreview(null);
    try {
      const res = await dispatchBulletinReminders({ slot, dry_run: dryRun, force: !dryRun && slot !== 'exact' });
      setDispatchPreview(res);
      showAppToast(res.message || 'Hoàn tất xử lý gửi nhắc', res.success ? 'success' : 'error');
      if (!dryRun) {
        await loadAdminStaffAndLogs();
      }
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi khi chạy gửi nhắc Zalo', 'error');
    } finally {
      setDispatching(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!sourceConfig) return;
    try {
      const saved = await updateBulletinConfig(sourceConfig);
      setSourceConfig(saved);
      showAppToast('Đã lưu cấu hình nguồn bản tin & lịch Zalo', 'success');
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi lưu cấu hình', 'error');
    }
  };

  const renderAdminMultiAssigneePicker = (
    selectedIds: number[],
    setSelectedIds: React.Dispatch<React.SetStateAction<number[]>>
  ) => {
    if (!isAdmin || staffList.length === 0) return null;
    const toggleId = (uid: number) => {
      setSelectedIds((prev) => (prev.includes(uid) ? prev.filter((x) => x !== uid) : [...prev, uid]));
    };
    return (
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="block text-xs font-semibold text-navy">
            Phân việc cho nhân sự (Admin — để trống = chính mình)
          </label>
          <div className="flex items-center gap-2 text-[11px]">
            <button
              type="button"
              onClick={() => setSelectedIds(staffList.filter((s) => s.role !== 'admin').map((s) => s.user_id))}
              className="text-brand-600 hover:underline font-semibold cursor-pointer"
            >
              Chọn tất cả NV
            </button>
            {selectedIds.length > 0 && (
              <button
                type="button"
                onClick={() => setSelectedIds([])}
                className="text-slate-400 hover:text-rose-600 cursor-pointer"
              >
                Bỏ chọn ({selectedIds.length})
              </button>
            )}
          </div>
        </div>
        <div className="max-h-28 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/70 p-2 flex flex-wrap gap-1.5">
          {staffList.map((s) => {
            const active = selectedIds.includes(s.user_id);
            return (
              <button
                key={s.user_id}
                type="button"
                onClick={() => toggleId(s.user_id)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-colors cursor-pointer ${
                  active
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-slate-700 border-slate-200 hover:bg-brand-50'
                }`}
              >
                {s.full_name}
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  const todayStr = getVnTodayStr(0);
  const clPct =
    checklistSummary.total_items > 0
      ? Math.round((checklistSummary.done_items / checklistSummary.total_items) * 100)
      : 0;

  const userDisplayName = currentUser?.full_name || currentUser?.username || 'EzTech';
  const userInitials = getInitials(userDisplayName);

  return (
    <div className="space-y-4">
      {/* FACEBOOK GROUP HEADER — Clean EzTech Card Surface (no cover overlap) */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden">
        {/* Group Identity Bar */}
        <div className="px-4 sm:px-6 pt-4 sm:pt-5 pb-3">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl bg-brand-50 border border-brand-100 flex items-center justify-center shrink-0 relative">
                <div className="w-full h-full rounded-2xl gradient-brand flex items-center justify-center text-white shadow-xs">
                  <Newspaper className="w-6 h-6 sm:w-7 sm:h-7" aria-hidden="true" />
                </div>
                <span
                  aria-hidden="true"
                  className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-gold-500 border-2 border-white flex items-center justify-center text-navy"
                >
                  <Check className="w-2.5 h-2.5 stroke-[3]" />
                </span>
              </div>

              <div className="min-w-0">
                <h2 className="text-lg sm:text-xl font-bold text-navy tracking-tight truncate">
                  Bảng Tin EzTech -Data & Finance Service
                </h2>
                <p className="text-xs text-slate-500 flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-0.5">
                  <span className="inline-flex items-center gap-1 font-medium text-slate-600">
                    <Globe className="w-3.5 h-3.5 text-brand-500" aria-hidden="true" />
                    Nhóm nội bộ Zalo
                  </span>
                </p>
              </div>
            </div>
          </div>

          {/* Facebook Group Navigation Tabs + Pill Search */}
          <div className="mt-4 pt-2 border-t border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
            <div role="tablist" aria-label="Lọc trạng thái đọc" className="flex items-center gap-1 -mb-3 sm:-mb-3">
              {([
                { key: 'all', label: 'Tất cả bài viết', count: totalAllPosts },
                { key: 'unread', label: 'Chưa đọc', count: unreadCount },
                { key: 'read', label: 'Đã đọc', count: Math.max(0, totalAllPosts - unreadCount) },
              ] as const).map((tab) => {
                const active = readFilter === tab.key;
                return (
                  <button
                    key={tab.key}
                    role="tab"
                    aria-selected={active}
                    type="button"
                    onClick={() => {
                      setReadFilter(tab.key);
                      setPostsPage(1);
                    }}
                    className={`relative px-3.5 py-2.5 text-xs font-semibold rounded-t-lg transition-colors cursor-pointer flex items-center gap-1.5 ${
                      active
                        ? 'text-brand-600'
                        : 'text-slate-500 hover:text-navy hover:bg-slate-50'
                    }`}
                  >
                    <span>{tab.label}</span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded-full font-mono tabular-nums ${
                        active
                          ? 'bg-brand-50 text-brand-700 font-bold'
                          : 'bg-slate-100 text-slate-500'
                      }`}
                    >
                      {tab.count}
                    </span>
                    {active && (
                      <span
                        aria-hidden="true"
                        className="absolute bottom-0 left-2 right-2 h-[3px] rounded-t-full bg-brand-500"
                      />
                    )}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto pb-1 sm:pb-0">
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={handleMarkAllRead}
                  disabled={markingAllRead}
                  className="px-2.5 py-1.5 rounded-full border border-brand-200 bg-brand-50/80 hover:bg-brand-100 text-[11px] font-semibold text-brand-700 flex items-center gap-1 shrink-0 transition-colors cursor-pointer disabled:opacity-50"
                  title="Đánh dấu tất cả bài viết chưa đọc là đã đọc"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>{markingAllRead ? 'Đang xử lý...' : 'Đánh dấu tất cả đã đọc'}</span>
                </button>
              )}

              <div className="relative flex-1 sm:w-60">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden="true" />
                <input
                  type="text"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="Tìm trong bảng tin..."
                  className="w-full pl-9 pr-8 py-1.5 rounded-full border border-slate-200 text-xs text-navy bg-slate-100/80 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-400 transition-all"
                />
                {searchInput && (
                  <button
                    type="button"
                    onClick={() => setSearchInput('')}
                    aria-label="Xóa từ khóa tìm kiếm"
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 rounded-full text-slate-400 hover:text-navy hover:bg-slate-200/70 cursor-pointer"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <ErrorBanner message={errorMsg} onRetry={() => loadPosts(postsPage)} />

      {/* Main 2-column Facebook Feed + Sticky Right Workplace Rail */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
        {/* LEFT COLUMN: FACEBOOK-STYLE NEWSFEED (7 cols) */}
        <section ref={feedSectionRef} className="xl:col-span-7 space-y-4">
          {/* 1. FACEBOOK STORIES / BOSS HIGHLIGHTS STRIP */}
          <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-3.5">
            <div className="flex items-center justify-between mb-2.5 px-1">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                Lọc nhanh theo Sếp
              </span>
              {bossFilter !== 'all' && (
                <button
                  type="button"
                  onClick={() => {
                    setBossFilter('all');
                    setPostsPage(1);
                  }}
                  className="text-[11px] font-semibold text-brand-600 hover:underline cursor-pointer"
                >
                  Xem tất cả
                </button>
              )}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {BOSS_FILTERS.map((b) => {
                const active = bossFilter === b.key;
                const count = b.key === 'all' ? totalAllPosts : bossCounts[b.key] || 0;
                const av = BOSS_AVATAR_MAP[b.key];
                return (
                  <button
                    key={b.key}
                    type="button"
                    onClick={() => {
                      setBossFilter(b.key);
                      setPostsPage(1);
                    }}
                    className={`group flex items-center gap-2.5 p-2 rounded-xl border text-left transition-all cursor-pointer ${
                      active
                        ? 'bg-brand-50 border-brand-300 ring-1 ring-brand-500/20 shadow-xs'
                        : 'bg-slate-50/70 border-slate-200/80 hover:bg-slate-100'
                    }`}
                  >
                    <div
                      className={`w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-transform duration-200 group-hover:scale-105 ${
                        av ? av.bg : 'gradient-brand text-white'
                      } ${active ? 'ring-2 ring-offset-2 ring-brand-500' : 'ring-2 ring-offset-1 ring-slate-200'}`}
                    >
                      {av ? av.initials : <Users className="w-4 h-4" aria-hidden="true" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className={`text-xs font-bold truncate ${active ? 'text-brand-700' : 'text-navy'}`}>
                        {av ? av.shortLabel : b.label}
                      </p>
                      <p className="text-[11px] text-slate-500 tabular-nums">{count} bài viết</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 2. FACEBOOK-STYLE QUICK ACTION COMPOSER CARD */}
          <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-3.5 sm:p-4 space-y-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full gradient-brand text-white font-bold text-xs flex items-center justify-center shrink-0 shadow-xs">
                {userInitials}
              </div>
              <button
                type="button"
                onClick={() => openChecklistModal(null)}
                className="flex-1 text-left px-4 py-2.5 rounded-full bg-slate-100 hover:bg-slate-200/80 text-xs sm:text-[13px] text-slate-500 transition-colors cursor-pointer"
              >
                {userDisplayName} ơi, tạo nhanh checklist công việc hoặc nhắc hẹn hôm nay...
              </button>
            </div>
            <div className="grid grid-cols-3 gap-1 pt-2 border-t border-slate-100">
              <button
                type="button"
                onClick={() => openChecklistModal(null)}
                className="flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 hover:text-navy transition-colors cursor-pointer"
              >
                <CheckSquare className="w-4 h-4 text-emerald-600 shrink-0" aria-hidden="true" />
                <span className="truncate">Checklist ngày</span>
              </button>
              <button
                type="button"
                onClick={() => openReminderModal(null, null)}
                className="flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 hover:text-navy transition-colors cursor-pointer"
              >
                <BellRing className="w-4 h-4 text-brand-500 shrink-0" aria-hidden="true" />
                <span className="truncate">Nhắc hẹn Zalo</span>
              </button>
              <button
                type="button"
                onClick={handleSyncGroup}
                disabled={syncingPosts}
                className="flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 hover:text-navy transition-colors cursor-pointer disabled:opacity-50"
              >
                <RefreshCw className={`w-4 h-4 text-gold-600 shrink-0 ${syncingPosts ? 'animate-spin' : ''}`} aria-hidden="true" />
                <span className="truncate">Đồng bộ tin mới</span>
              </button>
            </div>
          </div>

          {/* 3. FACEBOOK NEWSFEED POSTS */}
          {loadingPosts && posts.length === 0 ? (
            <div className="space-y-3">
              {[1, 2, 3].map((sk) => (
                <div key={sk} className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-4 space-y-3 animate-pulse">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-slate-200" />
                    <div className="space-y-1.5 flex-1">
                      <div className="h-3.5 bg-slate-200 rounded w-36" />
                      <div className="h-2.5 bg-slate-100 rounded w-24" />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="h-3 bg-slate-100 rounded w-full" />
                    <div className="h-3 bg-slate-100 rounded w-5/6" />
                    <div className="h-3 bg-slate-100 rounded w-2/3" />
                  </div>
                </div>
              ))}
            </div>
          ) : posts.length === 0 ? (
            <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-10 text-center space-y-2.5">
              <div className="w-12 h-12 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto text-slate-400">
                <Newspaper className="w-6 h-6" aria-hidden="true" />
              </div>
              <p className="text-sm font-bold text-navy">Chưa có bài viết nào phù hợp</p>
              <p className="text-xs text-slate-500 max-w-sm mx-auto">
                Bấm <strong>Đồng bộ nhóm Zalo</strong> để kéo thông báo mới nhất từ nhóm EzTech -Data & Finance Service.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {posts.map((post) => {
                const isLong = post.content.length > 420;
                const isExpanded = !!expandedPostIds[post.id];
                const displayContent = isLong && !isExpanded ? `${post.content.slice(0, 420)}...` : post.content;
                const bossBadgeCls = BOSS_BADGE_MAP[post.boss_key] || 'bg-slate-100 text-slate-700 border-slate-200';
                const bossAvatar = BOSS_AVATAR_MAP[post.boss_key];
                const authorName = post.sender_name || post.boss_display_name;
                const imageAttachments = (post.attachments || []).filter((att) => {
                  const targetUrl = att.url || att.link;
                  return !!targetUrl && (att.type === 'photo' || att.type === 'image' || /\.(png|jpe?g|webp|gif)(\?|$)/i.test(targetUrl));
                });
                const fileAttachments = (post.attachments || []).filter((att) => {
                  const targetUrl = att.url || att.link;
                  return !!targetUrl && !(att.type === 'photo' || att.type === 'image' || /\.(png|jpe?g|webp|gif)(\?|$)/i.test(targetUrl));
                });

                return (
                  <article
                    key={post.id}
                    className={`bg-white rounded-2xl border transition-all shadow-card hover:shadow-card-hover overflow-hidden ${
                      post.is_pinned
                        ? 'border-gold-400/90 ring-1 ring-gold-300/60'
                        : !post.is_read
                        ? 'border-brand-300/90'
                        : 'border-slate-200/80'
                    }`}
                  >
                    {/* Pinned strip (Facebook Group Pinned Post bar) */}
                    {post.is_pinned && (
                      <div className="px-4 py-1.5 bg-gold-50 border-b border-gold-200/80 flex items-center gap-1.5 text-[11px] font-bold text-gold-700">
                        <Pin className="w-3.5 h-3.5" aria-hidden="true" />
                        <span>Bài viết đã ghim bởi Quản trị viên</span>
                      </div>
                    )}

                    <div className="p-4 pb-2 space-y-3">
                      {/* Post Author Header */}
                      <div className="flex items-start justify-between gap-2.5">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="relative shrink-0">
                            <div
                              className={`w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold shadow-xs ${
                                bossAvatar ? bossAvatar.bg : 'gradient-brand text-white'
                              }`}
                            >
                              {bossAvatar ? bossAvatar.initials : getInitials(authorName)}
                            </div>
                            {!post.is_read && (
                              <span
                                title="Bản tin chưa đọc"
                                className="absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full bg-brand-500 border-2 border-white"
                              />
                            )}
                          </div>

                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <h3 className="text-[14px] font-bold text-navy leading-snug truncate">
                                {authorName}
                              </h3>
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${bossBadgeCls}`}>
                                Ban lãnh đạo
                              </span>
                            </div>
                            <div className="flex items-center gap-1.5 text-[11px] text-slate-500 mt-0.5">
                              <span className="font-mono">{post.posted_at}</span>
                              <span aria-hidden="true">·</span>
                              <Globe className="w-3 h-3 text-slate-400" aria-hidden="true" />
                              <span className="truncate">EzTech Group</span>
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-1 shrink-0">
                          {!post.is_read && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-brand-50 text-brand-700 border border-brand-200 text-[10px] font-bold">
                              Mới
                            </span>
                          )}
                          {isAdmin && (
                            <button
                              type="button"
                              onClick={() => handleTogglePin(post)}
                              title={post.is_pinned ? 'Bỏ ghim bài viết' : 'Ghim bài viết lên đầu'}
                              aria-label={post.is_pinned ? 'Bỏ ghim bài viết' : 'Ghim bài viết lên đầu'}
                              className={`p-2 rounded-full transition-colors cursor-pointer ${
                                post.is_pinned
                                  ? 'bg-gold-50 text-gold-700 hover:bg-gold-100'
                                  : 'text-slate-400 hover:text-navy hover:bg-slate-100'
                              }`}
                            >
                              <Pin className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Post Body Content */}
                      <div className="text-[14px] leading-[1.6] text-slate-800 whitespace-pre-wrap break-words">
                        {displayContent}
                        {isLong && (
                          <button
                            type="button"
                            onClick={() => setExpandedPostIds((prev) => ({ ...prev, [post.id]: !isExpanded }))}
                            className="ml-1.5 text-[13px] font-bold text-brand-600 hover:underline cursor-pointer"
                          >
                            {isExpanded ? 'Thu gọn' : 'Xem thêm'}
                          </button>
                        )}
                      </div>

                      {/* Facebook-Style Image Media Grid */}
                      {imageAttachments.length > 0 && (
                        <div
                          className={`grid gap-1.5 pt-1 ${
                            imageAttachments.length === 1
                              ? 'grid-cols-1'
                              : imageAttachments.length === 2
                              ? 'grid-cols-2'
                              : 'grid-cols-2 sm:grid-cols-3'
                          }`}
                        >
                          {imageAttachments.map((att, idx) => {
                            const targetUrl = att.url || att.link || '';
                            return (
                              <a
                                key={idx}
                                href={targetUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="group block overflow-hidden rounded-xl border border-slate-200/80 bg-slate-50"
                              >
                                <img
                                  src={targetUrl}
                                  alt={att.title || 'Ảnh đính kèm'}
                                  loading="lazy"
                                  className={`w-full object-cover transition-transform duration-300 group-hover:scale-[1.02] ${
                                    imageAttachments.length === 1 ? 'max-h-96' : 'h-44 sm:h-48'
                                  }`}
                                />
                              </a>
                            );
                          })}
                        </div>
                      )}

                      {/* Link / Document Attachment Cards */}
                      {fileAttachments.length > 0 && (
                        <div className="space-y-1.5 pt-1">
                          {fileAttachments.map((att, idx) => {
                            const targetUrl = att.url || att.link || '';
                            return (
                              <a
                                key={idx}
                                href={targetUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200/80 hover:bg-slate-100 transition-colors group"
                              >
                                <div className="w-9 h-9 rounded-lg bg-brand-50 text-brand-600 flex items-center justify-center shrink-0">
                                  <FileText className="w-4 h-4" aria-hidden="true" />
                                </div>
                                <div className="min-w-0 flex-1">
                                  <p className="text-xs font-semibold text-navy truncate group-hover:text-brand-600">
                                    {att.title || 'Tài liệu đính kèm'}
                                  </p>
                                  <p className="text-[11px] text-slate-400 truncate">{targetUrl}</p>
                                </div>
                                <ExternalLink className="w-3.5 h-3.5 text-slate-400 shrink-0" aria-hidden="true" />
                              </a>
                            );
                          })}
                        </div>
                      )}

                      {/* Social Stats / Engagement Summary Row */}
                      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 text-xs text-slate-500">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-brand-500 text-white">
                            <ThumbsUp className="w-2.5 h-2.5" aria-hidden="true" />
                          </span>
                          {isAdmin && post.read_count > 0 ? (
                            <button
                              type="button"
                              onClick={() => handleToggleReaders(post.id)}
                              className="inline-flex items-center gap-1 hover:underline hover:text-navy font-medium cursor-pointer"
                            >
                              <span>{post.read_count} người đã đọc</span>
                              {openReadersPostId === post.id ? (
                                <ChevronUp className="w-3.5 h-3.5" />
                              ) : (
                                <ChevronDown className="w-3.5 h-3.5" />
                              )}
                            </button>
                          ) : (
                            <span>{post.read_count} người đã đọc</span>
                          )}
                        </div>

                        <div className="flex items-center gap-3 text-[11px]">
                          {post.my_reminder_count > 0 && (
                            <span className="inline-flex items-center gap-1 text-brand-600 font-semibold">
                              <Clock className="w-3 h-3" aria-hidden="true" />
                              {post.my_reminder_count} nhắc hẹn
                            </span>
                          )}
                          {post.my_checklist_count > 0 && (
                            <span className="inline-flex items-center gap-1 text-emerald-600 font-semibold">
                              <CheckSquare className="w-3 h-3" aria-hidden="true" />
                              {post.my_checklist_count} checklist
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Admin Readers Drawer (lazy-loaded on click) */}
                      {isAdmin && openReadersPostId === post.id && (
                        <div className="bg-slate-50 rounded-xl p-2.5 border border-slate-200/80 space-y-1.5">
                          <p className="text-[11px] font-semibold text-slate-500 flex items-center gap-1">
                            <Eye className="w-3 h-3 text-brand-500" aria-hidden="true" />
                            Nhân sự đã xác nhận đọc:
                          </p>
                          {loadingReadersPostId === post.id ? (
                            <p className="text-[11px] text-slate-400">Đang tải danh sách...</p>
                          ) : (
                            <div className="flex flex-wrap gap-1.5">
                              {(postReadersMap[post.id] || post.readers || []).map((r) => (
                                <span
                                  key={r.user_id}
                                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white border border-slate-200 text-[11px] font-medium text-slate-700"
                                  title={`Đọc lúc: ${r.read_at || ''}`}
                                >
                                  <span className="w-4 h-4 rounded-full bg-emerald-100 text-emerald-700 text-[9px] font-bold flex items-center justify-center">
                                    {getInitials(r.full_name)}
                                  </span>
                                  {r.full_name}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Facebook-Style Flat 4-Action Footer Bar */}
                    <div className="px-2 py-1.5 border-t border-slate-100 grid grid-cols-2 sm:grid-cols-4 gap-1">
                      <button
                        type="button"
                        onClick={() => handleToggleRead(post)}
                        className={`flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold transition-colors cursor-pointer ${
                          post.is_read
                            ? 'text-brand-600 bg-brand-50/70 hover:bg-brand-100/70'
                            : 'text-slate-600 hover:bg-slate-100 hover:text-navy'
                        }`}
                      >
                        <ThumbsUp className={`w-4 h-4 shrink-0 ${post.is_read ? 'fill-brand-500/20' : ''}`} aria-hidden="true" />
                        <span className="truncate">{post.is_read ? 'Đã đọc' : 'Đánh dấu đọc'}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => openReminderModal(post, null)}
                        className="flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 hover:text-brand-600 transition-colors cursor-pointer"
                      >
                        <Clock className="w-4 h-4 shrink-0" aria-hidden="true" />
                        <span className="truncate">Nhắc hẹn</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => openChecklistModal(post)}
                        className="flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 hover:text-emerald-600 transition-colors cursor-pointer"
                      >
                        <CheckSquare className="w-4 h-4 shrink-0" aria-hidden="true" />
                        <span className="truncate">Checklist</span>
                      </button>

                      <button
                        type="button"
                        disabled={aiLoadingPostId === post.id}
                        onClick={() => handleAiExtract(post)}
                        className="flex items-center justify-center gap-1.5 py-2 px-2 rounded-xl text-xs font-semibold text-purple-700 hover:bg-purple-50 transition-colors cursor-pointer disabled:opacity-50"
                      >
                        <Sparkles className={`w-4 h-4 shrink-0 ${aiLoadingPostId === post.id ? 'animate-spin' : ''}`} aria-hidden="true" />
                        <span className="truncate">{aiLoadingPostId === post.id ? 'Đang tách...' : 'AI tách việc'}</span>
                      </button>
                    </div>
                  </article>
                );
              })}

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex flex-wrap items-center justify-between gap-2 bg-white rounded-2xl border border-slate-200/80 shadow-card px-4 py-3 text-xs">
                  <span className="text-slate-500 tabular-nums">
                    Trang <strong className="text-navy">{postsPage}</strong> / {totalPages} ({postsTotal} bài viết)
                  </span>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <button
                      type="button"
                      disabled={postsPage <= 1 || loadingPosts}
                      onClick={() => handleChangePostsPage(postsPage - 1)}
                      className="px-3 py-1.5 rounded-xl border border-slate-200 font-semibold text-navy hover:bg-slate-50 disabled:opacity-40 cursor-pointer transition-colors"
                    >
                      Trước
                    </button>
                    {Array.from({ length: totalPages }, (_, i) => i + 1)
                      .filter((p) => p === 1 || p === totalPages || Math.abs(p - postsPage) <= 1)
                      .map((p, idx, arr) => {
                        const prevPage = arr[idx - 1];
                        const showEllipsis = prevPage !== undefined && p - prevPage > 1;
                        return (
                          <span key={p} className="inline-flex items-center gap-1">
                            {showEllipsis && <span className="px-1 text-slate-400">...</span>}
                            <button
                              type="button"
                              disabled={loadingPosts}
                              onClick={() => handleChangePostsPage(p)}
                              className={`min-w-[30px] h-7 px-2 rounded-lg font-semibold tabular-nums transition-colors cursor-pointer ${
                                p === postsPage
                                  ? 'bg-brand-500 text-white shadow-xs'
                                  : 'border border-slate-200 text-navy hover:bg-slate-50'
                              }`}
                            >
                              {p}
                            </button>
                          </span>
                        );
                      })}
                    <button
                      type="button"
                      disabled={postsPage >= totalPages || loadingPosts}
                      onClick={() => handleChangePostsPage(postsPage + 1)}
                      className="px-3 py-1.5 rounded-xl border border-slate-200 font-semibold text-navy hover:bg-slate-50 disabled:opacity-40 cursor-pointer transition-colors"
                    >
                      Sau
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {/* RIGHT COLUMN: WORKPLACE RAIL + FULL MONTH CALENDAR (5 cols) */}
        <aside className="xl:col-span-5 space-y-4">
          <div ref={workspaceRef} className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden scroll-mt-20">
            {/* Rail Title + Segmented Underline Tabs */}
            <div className="px-4 pt-3.5 pb-0 border-b border-slate-100">
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                  <ListTodo className="w-3.5 h-3.5 text-brand-500" aria-hidden="true" />
                  <span>Không gian công việc</span>
                </h3>
                <span className="text-[11px] font-mono text-slate-400 tabular-nums">
                  {checklistSummary.done_items}/{checklistSummary.total_items} việc • {pendingRemindersCount} hẹn
                </span>
              </div>

              <div role="tablist" aria-label="Công cụ công việc" className="flex items-center gap-1">
                <button
                  role="tab"
                  aria-selected={workTab === 'checklist'}
                  type="button"
                  onClick={() => setWorkTab('checklist')}
                  className={`relative flex-1 py-2.5 px-2 rounded-t-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
                    workTab === 'checklist'
                      ? 'text-brand-600'
                      : 'text-slate-500 hover:text-navy hover:bg-slate-50'
                  }`}
                >
                  <ListTodo className="w-3.5 h-3.5 text-emerald-600 shrink-0" aria-hidden="true" />
                  <span className="truncate">Checklist</span>
                  {checklistSummary.total_items > 0 && (
                    <span className="px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-bold font-mono tabular-nums">
                      {checklistSummary.done_items}/{checklistSummary.total_items}
                    </span>
                  )}
                  {workTab === 'checklist' && (
                    <span aria-hidden="true" className="absolute bottom-0 left-2 right-2 h-[3px] rounded-t-full bg-brand-500" />
                  )}
                </button>

                <button
                  role="tab"
                  aria-selected={workTab === 'reminders'}
                  type="button"
                  onClick={() => setWorkTab('reminders')}
                  className={`relative flex-1 py-2.5 px-2 rounded-t-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
                    workTab === 'reminders'
                      ? 'text-brand-600'
                      : 'text-slate-500 hover:text-navy hover:bg-slate-50'
                  }`}
                >
                  <Bell className="w-3.5 h-3.5 text-brand-500 shrink-0" aria-hidden="true" />
                  <span className="truncate">Nhắc hẹn</span>
                  {pendingRemindersCount > 0 && (
                    <span className="px-1.5 py-0.5 rounded-full bg-brand-50 text-brand-700 text-[10px] font-bold font-mono tabular-nums">
                      {pendingRemindersCount}
                    </span>
                  )}
                  {workTab === 'reminders' && (
                    <span aria-hidden="true" className="absolute bottom-0 left-2 right-2 h-[3px] rounded-t-full bg-brand-500" />
                  )}
                </button>

                {isAdmin && (
                  <button
                    role="tab"
                    aria-selected={workTab === 'admin'}
                    type="button"
                    onClick={() => setWorkTab('admin')}
                    className={`relative flex-1 py-2.5 px-2 rounded-t-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
                      workTab === 'admin'
                        ? 'text-brand-600'
                        : 'text-slate-500 hover:text-navy hover:bg-slate-50'
                    }`}
                  >
                    <Settings className="w-3.5 h-3.5 text-gold-600 shrink-0" aria-hidden="true" />
                    <span className="truncate">Zalo & Admin</span>
                    {workTab === 'admin' && (
                      <span aria-hidden="true" className="absolute bottom-0 left-2 right-2 h-[3px] rounded-t-full bg-brand-500" />
                    )}
                  </button>
                )}
              </div>
            </div>

            {/* Admin Global Staff Filter Bar */}
            {isAdmin && workTab !== 'admin' && (
              <div className="px-4 py-2.5 bg-amber-50/50 border-b border-amber-200/60 flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-amber-800 flex items-center gap-1">
                  <Users className="w-3.5 h-3.5" />
                  Admin xem nhân sự:
                </span>
                <select
                  value={adminOwnerFilter}
                  onChange={(e) => setAdminOwnerFilter(e.target.value)}
                  className="text-xs font-medium bg-white border border-amber-200 rounded-lg px-2.5 py-1 text-navy focus:outline-none"
                >
                  <option value="">Tất cả nhân sự EzTech</option>
                  {staffList.map((s) => (
                    <option key={s.user_id} value={String(s.user_id)}>
                      {s.full_name} ({s.department})
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* TAB 1: DAILY CHECKLIST */}
            {workTab === 'checklist' && (
              <div className="p-4 space-y-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-emerald-600" />
                    <input
                      type="date"
                      value={checklistDate}
                      onChange={(e) => setChecklistDate(e.target.value)}
                      className="text-xs font-mono font-semibold text-navy bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => openChecklistModal(null)}
                    className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Thêm checklist</span>
                  </button>
                </div>

                {/* A3: Rollover Banner */}
                {checklistDate === todayStr && rolloverItems.length > 0 && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-3 flex items-center justify-between gap-2">
                    <div className="space-y-0.5 min-w-0">
                      <p className="text-xs font-bold text-amber-900 flex items-center gap-1.5">
                        <CornerDownRight className="w-3.5 h-3.5 shrink-0" />
                        Còn {rolloverItems.length} việc chưa xong từ hôm trước
                      </p>
                      <p className="text-[11px] text-amber-700 truncate">
                        {rolloverItems.slice(0, 2).map((x) => x.content).join(' • ')}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={rollingOver}
                      onClick={handleRolloverPending}
                      className="px-2.5 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-semibold shrink-0 cursor-pointer disabled:opacity-50"
                    >
                      {rollingOver ? 'Đang chuyển...' : 'Chuyển sang hôm nay'}
                    </button>
                  </div>
                )}

                {/* Progress Bar */}
                <div className="bg-slate-50 rounded-xl p-3 border border-slate-200/80 space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-navy">Tiến độ trong ngày</span>
                    <span className="font-mono font-bold text-emerald-700">
                      {checklistSummary.done_items}/{checklistSummary.total_items} ({clPct}%)
                    </span>
                  </div>
                  <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-500 transition-all duration-300"
                      style={{ width: `${clPct}%` }}
                    />
                  </div>
                </div>

                {loadingChecklists && checklists.length === 0 ? (
                  <p className="text-xs text-slate-400 text-center py-6">Đang tải checklist...</p>
                ) : checklists.length === 0 ? (
                  <div className="text-center py-8 space-y-2">
                    <CheckSquare className="w-8 h-8 text-slate-300 mx-auto" />
                    <p className="text-xs text-slate-500">Chưa có checklist công việc nào cho ngày này.</p>
                  </div>
                ) : (
                  <div className="space-y-3 max-h-[620px] overflow-y-auto pr-1">
                    {checklists.map((cl) => (
                      <div key={cl.id} className="rounded-xl border border-slate-200/90 bg-white p-3 space-y-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <div className="space-y-1 min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <h4 className="text-xs font-bold text-navy truncate">{cl.title}</h4>
                              {cl.is_recurring_daily && (
                                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200 text-[10px] font-semibold">
                                  <Repeat className="w-2.5 h-2.5" /> Lặp mỗi ngày
                                </span>
                              )}
                            </div>
                            <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                              {isAdmin && cl.owner_name && (
                                <span className="font-medium text-slate-600">NV: {cl.owner_name}</span>
                              )}
                              {cl.source_post_boss && (
                                <span className="text-brand-600">Từ tin {cl.source_post_boss}</span>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {isAdmin && (
                              <button
                                type="button"
                                onClick={() => {
                                  setEditingNoteChecklistId(cl.id);
                                  setEditingNoteText(cl.admin_note || '');
                                }}
                                title={cl.admin_note ? 'Sửa ghi chú cho nhân viên' : 'Thêm ghi chú cho nhân viên'}
                                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-semibold border transition-colors cursor-pointer ${
                                  cl.admin_note
                                    ? 'bg-amber-50 text-amber-800 border-amber-200 hover:bg-amber-100'
                                    : 'bg-slate-50 text-slate-500 border-slate-200 hover:text-amber-800 hover:bg-amber-50 hover:border-amber-200'
                                }`}
                              >
                                <StickyNote className="w-3 h-3" aria-hidden="true" />
                                <span>{cl.admin_note ? 'Sửa note' : '+ Note'}</span>
                              </button>
                            )}
                            <span className="text-[11px] font-mono font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">
                              {cl.done_count}/{cl.total_count}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleDeleteChecklist(cl.id)}
                              title="Xóa checklist"
                              className="p-1 text-slate-400 hover:text-rose-600 cursor-pointer"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>

                        {/* Admin Note cho nhân viên */}
                        {editingNoteChecklistId === cl.id ? (
                          <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-2 space-y-1.5">
                            <textarea
                              rows={2}
                              autoFocus
                              value={editingNoteText}
                              onChange={(e) => setEditingNoteText(e.target.value)}
                              placeholder="Nhập ghi chú (Note) của Admin dành cho nhân viên..."
                              className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-amber-200 bg-white text-navy focus:outline-none focus:ring-2 focus:ring-amber-400/30"
                            />
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => {
                                  setEditingNoteChecklistId(null);
                                  setEditingNoteText('');
                                }}
                                disabled={savingChecklistNote}
                                className="px-2.5 py-1 rounded-lg border border-slate-200 bg-white text-[11px] font-semibold text-slate-600 hover:bg-slate-50 cursor-pointer"
                              >
                                Hủy
                              </button>
                              <button
                                type="button"
                                disabled={savingChecklistNote}
                                onClick={() => handleSaveChecklistAdminNote(cl.id)}
                                className="px-2.5 py-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-semibold cursor-pointer disabled:opacity-50"
                              >
                                {savingChecklistNote ? 'Đang lưu...' : 'Lưu note'}
                              </button>
                            </div>
                          </div>
                        ) : cl.admin_note ? (
                          <div className="rounded-lg border border-amber-200/80 bg-amber-50/70 px-2.5 py-2 flex items-start gap-2 text-xs text-amber-900">
                            <StickyNote className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-[1px]" aria-hidden="true" />
                            <div className="min-w-0 flex-1 whitespace-pre-wrap break-words text-[11px] leading-4">
                              <span className="font-bold">
                                {cl.admin_note_by ? `Note (${cl.admin_note_by}): ` : 'Note Admin: '}
                              </span>
                              <span>{cl.admin_note}</span>
                            </div>
                          </div>
                        ) : null}

                        {/* Items */}
                        <div className="space-y-1.5">
                          {cl.items.map((item) => (
                            <div
                              key={item.id}
                              className="flex items-center justify-between gap-2 group py-1 px-1.5 rounded-lg hover:bg-slate-50"
                            >
                              {editingItemId === item.id ? (
                                <div className="flex items-center gap-1.5 flex-1">
                                  <input
                                    type="text"
                                    autoFocus
                                    value={editingItemText}
                                    onChange={(e) => setEditingItemText(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') {
                                        e.preventDefault();
                                        handleSaveEditChecklistItem(item.id);
                                      } else if (e.key === 'Escape') {
                                        setEditingItemId(null);
                                      }
                                    }}
                                    className="flex-1 text-xs px-2 py-1 rounded border border-brand-400 bg-white focus:outline-none"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => handleSaveEditChecklistItem(item.id)}
                                    className="px-2 py-1 rounded bg-brand-600 text-white text-[10px] font-semibold cursor-pointer"
                                  >
                                    Lưu
                                  </button>
                                </div>
                              ) : (
                                <>
                                  <button
                                    type="button"
                                    onClick={() => handleToggleChecklistItem(cl.id, item.id, item.is_done)}
                                    className="flex items-start gap-2 text-left flex-1 min-w-0 cursor-pointer"
                                  >
                                    {item.is_done ? (
                                      <CheckSquare className="w-4 h-4 text-emerald-600 shrink-0" />
                                    ) : (
                                      <Square className="w-4 h-4 text-slate-400 shrink-0" />
                                    )}
                                    <span className="min-w-0 flex-1 flex flex-col">
                                      <span
                                        className={`block text-xs leading-4 break-words ${
                                          item.is_done ? 'line-through text-slate-400' : 'text-slate-700 font-medium'
                                        }`}
                                      >
                                        {item.content}
                                      </span>
                                      {item.note && (
                                        <span className="block text-[10px] leading-3.5 text-slate-400 mt-0.5">
                                          {item.note}
                                        </span>
                                      )}
                                    </span>
                                  </button>
                                  <div className="flex items-center gap-1 shrink-0">
                                    <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setEditingItemId(item.id);
                                          setEditingItemText(item.content);
                                        }}
                                        className="p-0.5 text-slate-400 hover:text-brand-600 cursor-pointer"
                                        title="Sửa đầu việc"
                                      >
                                        <Pencil className="w-3 h-3" />
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => handleDeleteChecklistItem(item.id)}
                                        className="p-0.5 text-slate-400 hover:text-rose-600 cursor-pointer"
                                        title="Xóa đầu việc"
                                      >
                                        <Trash2 className="w-3 h-3" />
                                      </button>
                                    </div>
                                    {item.is_assigned && (
                                      <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-300/90 whitespace-nowrap">
                                        Task được giao
                                      </span>
                                    )}
                                  </div>
                                </>
                              )}
                            </div>
                          ))}
                        </div>

                        {/* Inline Add Item */}
                        <div className="flex items-center gap-1.5 pt-1 border-t border-slate-100">
                          <input
                            type="text"
                            value={inlineItemInputs[cl.id] || ''}
                            onChange={(e) => setInlineItemInputs((prev) => ({ ...prev, [cl.id]: e.target.value }))}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                handleAddInlineItem(cl.id);
                              }
                            }}
                            placeholder="+ Thêm đầu việc rồi nhấn Enter..."
                            className="flex-1 text-xs px-2.5 py-1.5 rounded-lg bg-slate-50 border border-slate-200 focus:bg-white focus:outline-none focus:border-emerald-400"
                          />
                          <button
                            type="button"
                            onClick={() => handleAddInlineItem(cl.id)}
                            className="px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-emerald-50 text-slate-700 hover:text-emerald-700 text-xs font-semibold cursor-pointer"
                          >
                            Thêm
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: REMINDERS */}
            {workTab === 'reminders' && (
              <div className="p-4 space-y-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="inline-flex rounded-xl border border-slate-200 p-0.5 bg-slate-50">
                    {(['pending', 'completed', 'all'] as const).map((st) => (
                      <button
                        key={st}
                        type="button"
                        onClick={() => setReminderStatusFilter(st)}
                        className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold cursor-pointer ${
                          reminderStatusFilter === st ? 'bg-white text-navy shadow-xs' : 'text-slate-500'
                        }`}
                      >
                        {st === 'pending' ? 'Chưa xong' : st === 'completed' ? 'Đã xong' : 'Tất cả'}
                      </button>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={() => openReminderModal(null, null)}
                    className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Nhắc hẹn mới</span>
                  </button>
                </div>

                {loadingReminders && reminders.length === 0 ? (
                  <p className="text-xs text-slate-400 text-center py-6">Đang tải nhắc hẹn...</p>
                ) : reminders.length === 0 ? (
                  <div className="text-center py-8 space-y-2">
                    <Bell className="w-8 h-8 text-slate-300 mx-auto" />
                    <p className="text-xs text-slate-500">Không có nhắc hẹn nào trong mục này.</p>
                  </div>
                ) : (
                  <div className="space-y-2.5 max-h-[620px] overflow-y-auto pr-1">
                    {reminders.map((rem) => {
                      const isOverdue = rem.status === 'pending' && rem.due_date < todayStr;
                      const prio = PRIORITY_BADGE_MAP[rem.priority] || PRIORITY_BADGE_MAP.normal;
                      const recRule = rem.recurrence_rule || 'none';
                      return (
                        <div
                          key={rem.id}
                          className={`rounded-xl border p-3 space-y-2 ${
                            rem.status === 'completed'
                              ? 'bg-slate-50/70 border-slate-200/70 opacity-80'
                              : isOverdue
                              ? 'bg-rose-50/30 border-rose-200'
                              : 'bg-white border-slate-200'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="space-y-1 min-w-0">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${prio.cls}`}>
                                  {prio.label}
                                </span>
                                {recRule !== 'none' && (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200 text-[10px] font-semibold">
                                    <Repeat className="w-2.5 h-2.5" /> {RECURRENCE_LABELS[recRule]}
                                  </span>
                                )}
                                {isOverdue && (
                                  <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 text-[10px] font-bold">
                                    <AlertCircle className="w-3 h-3" /> Quá hạn
                                  </span>
                                )}
                                <span className="text-[11px] font-mono text-slate-500">{rem.remind_at_display}</span>
                              </div>
                              <p
                                className={`text-xs font-bold ${
                                  rem.status === 'completed' ? 'line-through text-slate-400' : 'text-navy'
                                }`}
                              >
                                {rem.title}
                              </p>
                              {rem.description && (
                                <p className="text-[11px] text-slate-500 line-clamp-2">{rem.description}</p>
                              )}
                            </div>

                            <div className="flex items-center gap-1 shrink-0">
                              <button
                                type="button"
                                onClick={() => openReminderModal(null, rem)}
                                title="Sửa nhắc hẹn"
                                className="p-1.5 rounded-lg border border-slate-200 text-slate-400 hover:text-brand-600 cursor-pointer"
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => handleToggleReminderStatus(rem)}
                                title={rem.status === 'completed' ? 'Mở lại' : 'Đánh dấu hoàn thành'}
                                className={`p-1.5 rounded-lg border text-xs cursor-pointer ${
                                  rem.status === 'completed'
                                    ? 'bg-emerald-100 border-emerald-300 text-emerald-700'
                                    : 'bg-white border-slate-200 text-slate-500 hover:bg-emerald-50 hover:text-emerald-700'
                                }`}
                              >
                                <Check className="w-3.5 h-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDeleteReminder(rem.id)}
                                title="Xóa nhắc hẹn"
                                className="p-1.5 rounded-lg border border-slate-200 text-slate-400 hover:text-rose-600 cursor-pointer"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </div>

                          {/* A4: Quick Snooze bar for pending reminders */}
                          {rem.status === 'pending' && (
                            <div className="flex flex-wrap items-center gap-1 text-[10px]">
                              <span className="text-slate-400 mr-0.5">Hoãn nhanh:</span>
                              <button
                                type="button"
                                onClick={() => handleSnoozeReminder(rem, getDefaultRemindAt(30), '+30 phút')}
                                className="px-2 py-0.5 rounded bg-slate-100 hover:bg-brand-50 hover:text-brand-700 text-slate-600 font-semibold cursor-pointer"
                              >
                                +30p
                              </button>
                              <button
                                type="button"
                                onClick={() => handleSnoozeReminder(rem, getDefaultRemindAt(60), '+1 giờ')}
                                className="px-2 py-0.5 rounded bg-slate-100 hover:bg-brand-50 hover:text-brand-700 text-slate-600 font-semibold cursor-pointer"
                              >
                                +1h
                              </button>
                              <button
                                type="button"
                                onClick={() => handleSnoozeReminder(rem, getTodayPresetTime('15:00'), '15:00 hôm nay')}
                                className="px-2 py-0.5 rounded bg-slate-100 hover:bg-brand-50 hover:text-brand-700 text-slate-600 font-semibold cursor-pointer"
                              >
                                15:00
                              </button>
                              <button
                                type="button"
                                onClick={() => handleSnoozeReminder(rem, getTodayPresetTime('09:00', 1), '09:00 ngày mai')}
                                className="px-2 py-0.5 rounded bg-slate-100 hover:bg-brand-50 hover:text-brand-700 text-slate-600 font-semibold cursor-pointer"
                              >
                                Mai 09:00
                              </button>
                            </div>
                          )}

                          <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500 pt-1 border-t border-slate-100">
                            {isAdmin && rem.owner_name && (
                              <span className="font-semibold text-navy">NV: {rem.owner_name}</span>
                            )}
                            {rem.source_post_boss && (
                              <span className="text-brand-600 font-medium">Từ tin: {rem.source_post_boss}</span>
                            )}
                            <span className="ml-auto flex items-center gap-1">
                              {rem.notify_11h && <span className="px-1.5 py-0.5 rounded bg-slate-100">11h</span>}
                              {rem.notify_15h && <span className="px-1.5 py-0.5 rounded bg-slate-100">15h</span>}
                              {rem.notify_exact_time && (
                                <span className="px-1.5 py-0.5 rounded bg-brand-50 text-brand-700">
                                  {rem.exact_notified_at ? 'Đã báo đúng giờ' : 'Báo đúng giờ'}
                                </span>
                              )}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: ADMIN ZALO & CONFIG */}
            {workTab === 'admin' && isAdmin && (
              <div className="p-4 space-y-4 max-h-[680px] overflow-y-auto">
                {/* Dispatch Controls */}
                <div className="rounded-xl border border-brand-200 bg-brand-50/40 p-3 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-bold text-navy">Gửi nhắc Zalo qua Eztech Consultant</h4>
                    <span className="text-[10px] font-mono text-slate-500">11:00 & 15:00 + Đúng giờ</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      disabled={dispatching}
                      onClick={() => handleDispatch('11h', true)}
                      className="px-2.5 py-1.5 rounded-lg bg-white border border-slate-200 text-[11px] font-semibold text-navy hover:bg-slate-50 cursor-pointer disabled:opacity-50"
                    >
                      Xem trước (11h)
                    </button>
                    <button
                      type="button"
                      disabled={dispatching}
                      onClick={() => handleDispatch('15h', true)}
                      className="px-2.5 py-1.5 rounded-lg bg-white border border-slate-200 text-[11px] font-semibold text-navy hover:bg-slate-50 cursor-pointer disabled:opacity-50"
                    >
                      Xem trước (15h)
                    </button>
                    <button
                      type="button"
                      disabled={dispatching}
                      onClick={() => handleDispatch('11h', false)}
                      className="px-2.5 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-[11px] font-semibold flex items-center justify-center gap-1 cursor-pointer disabled:opacity-50"
                    >
                      <Send className="w-3 h-3" /> Gửi 11h ngay
                    </button>
                    <button
                      type="button"
                      disabled={dispatching}
                      onClick={() => handleDispatch('15h', false)}
                      className="px-2.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-semibold flex items-center justify-center gap-1 cursor-pointer disabled:opacity-50"
                    >
                      <Send className="w-3 h-3" /> Gửi 15h ngay
                    </button>
                  </div>
                  <button
                    type="button"
                    disabled={dispatching}
                    onClick={() => handleDispatch('exact', false)}
                    className="w-full px-2.5 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-semibold cursor-pointer disabled:opacity-50"
                  >
                    Kiểm tra & gửi nhắc hẹn đúng giờ đến hạn
                  </button>

                  {dispatchPreview && (
                    <div className="bg-white rounded-lg border border-slate-200 p-2.5 text-[11px] space-y-1.5 max-h-48 overflow-y-auto">
                      <p className="font-bold text-navy">{dispatchPreview.message}</p>
                      {(dispatchPreview.results || []).map((r: any, i: number) => (
                        <div key={i} className="border-t border-slate-100 pt-1">
                          <div className="flex justify-between font-semibold">
                            <span>{r.staff_name || `Reminder #${r.reminder_id}`}</span>
                            <span className={r.status === 'FAILED' ? 'text-rose-600' : 'text-emerald-700'}>{r.status}</span>
                          </div>
                          {r.reason && <p className="text-slate-400">{r.reason}</p>}
                          {r.error_message && <p className="text-rose-600">{r.error_message}</p>}
                          {r.preview_message && (
                            <pre className="mt-1 whitespace-pre-wrap text-[10px] bg-slate-50 p-2 rounded border border-slate-200 text-slate-700">
                              {r.preview_message}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Staff Zalo Directory */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="text-xs font-bold text-navy">Danh bạ nhân viên & Zalo Eztech Consultant</h4>
                    <button
                      type="button"
                      disabled={scanningContacts}
                      onClick={handleScanZaloContacts}
                      className="px-2.5 py-1 rounded-lg bg-navy text-white text-[11px] font-semibold cursor-pointer disabled:opacity-50"
                    >
                      {scanningContacts ? 'Đang quét...' : 'Quét hội thoại Zalo'}
                    </button>
                  </div>

                  <div className="space-y-2">
                    {staffList.map((st) => (
                      <div key={st.user_id} className="rounded-xl border border-slate-200 p-2.5 space-y-2 bg-slate-50/40">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-xs font-bold text-navy">{st.full_name}</p>
                            <p className="text-[10px] text-slate-400">
                              @{st.username} • {st.department}
                            </p>
                          </div>
                          <label className="flex items-center gap-1 text-[11px] text-slate-600 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={st.receive_daily_digest}
                              onChange={(e) => {
                                const val = e.target.checked;
                                setStaffList((prev) =>
                                  prev.map((x) => (x.user_id === st.user_id ? { ...x, receive_daily_digest: val } : x))
                                );
                              }}
                            />
                            Nhận 11h/15h
                          </label>
                        </div>

                        {zaloContacts.length > 0 && (
                          <select
                            value={st.zalo_conversation_id || ''}
                            onChange={(e) => {
                              const cid = e.target.value;
                              const picked = zaloContacts.find((c) => c.conversation_id === cid);
                              setStaffList((prev) =>
                                prev.map((x) =>
                                  x.user_id === st.user_id
                                    ? {
                                        ...x,
                                        zalo_conversation_id: cid,
                                        zalo_display_name: picked?.display_name || x.zalo_display_name,
                                        phone_number: x.phone_number || picked?.phone_number || null,
                                      }
                                    : x
                                )
                              );
                            }}
                            className="w-full text-[11px] bg-white border border-slate-200 rounded-lg px-2 py-1"
                          >
                            <option value="">-- Chọn hội thoại Zalo trên Eztech Consultant --</option>
                            {zaloContacts.map((c) => (
                              <option key={c.conversation_id} value={c.conversation_id}>
                                {c.display_name} {c.phone_number ? `(${c.phone_number})` : ''} — {c.conversation_id}
                              </option>
                            ))}
                          </select>
                        )}

                        <div className="grid grid-cols-2 gap-1.5">
                          <input
                            type="text"
                            value={st.zalo_conversation_id || ''}
                            onChange={(e) => {
                              const val = e.target.value;
                              setStaffList((prev) =>
                                prev.map((x) => (x.user_id === st.user_id ? { ...x, zalo_conversation_id: val } : x))
                              );
                            }}
                            placeholder="pzl_u_764881945463506349_..."
                            className="text-[11px] font-mono bg-white border border-slate-200 rounded-lg px-2 py-1"
                          />
                          <input
                            type="text"
                            value={st.phone_number || ''}
                            onChange={(e) => {
                              const val = e.target.value;
                              setStaffList((prev) =>
                                prev.map((x) => (x.user_id === st.user_id ? { ...x, phone_number: val } : x))
                              );
                            }}
                            placeholder="SĐT Zalo (tuỳ chọn)"
                            className="text-[11px] bg-white border border-slate-200 rounded-lg px-2 py-1"
                          />
                        </div>

                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => handleTestStaffZalo(st.user_id)}
                            disabled={!st.zalo_conversation_id}
                            className="px-2.5 py-1 rounded-lg border border-slate-200 bg-white text-[11px] font-semibold text-navy hover:bg-slate-50 cursor-pointer disabled:opacity-40"
                          >
                            Test Zalo
                          </button>
                          <button
                            type="button"
                            onClick={() => handleSaveStaffMapping(st)}
                            className="px-2.5 py-1 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-[11px] font-semibold cursor-pointer"
                          >
                            Lưu
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Source Group & Schedule Config */}
                {sourceConfig && (
                  <div className="rounded-xl border border-slate-200 p-3 space-y-2.5">
                    <h4 className="text-xs font-bold text-navy">Cấu hình nhóm Zalo & Lịch nhắc</h4>
                    <input
                      type="text"
                      value={sourceConfig.group_name || ''}
                      onChange={(e) => setSourceConfig({ ...sourceConfig, group_name: e.target.value })}
                      placeholder="Tên nhóm Zalo"
                      className="w-full text-xs border border-slate-200 rounded-lg px-2.5 py-1.5"
                    />
                    <input
                      type="text"
                      value={sourceConfig.group_conversation_id || ''}
                      onChange={(e) => setSourceConfig({ ...sourceConfig, group_conversation_id: e.target.value })}
                      placeholder="ID nhóm pzl_g_... (tự điền khi đồng bộ)"
                      className="w-full text-xs font-mono border border-slate-200 rounded-lg px-2.5 py-1.5"
                    />
                    <input
                      type="text"
                      value={sourceConfig.dashboard_url || ''}
                      onChange={(e) => setSourceConfig({ ...sourceConfig, dashboard_url: e.target.value })}
                      placeholder="URL Dashboard gắn cuối tin Zalo (VD: https://...)"
                      className="w-full text-xs border border-slate-200 rounded-lg px-2.5 py-1.5"
                    />
                    <div className="space-y-1">
                      <p className="text-[11px] font-semibold text-slate-600">Ngày gửi nhắc tự động 11h & 15h:</p>
                      <div className="flex flex-wrap gap-1.5">
                        {WEEKDAY_OPTIONS.map((w) => {
                          const days: number[] = sourceConfig.active_weekdays || [0, 1, 2, 3, 4, 5];
                          const active = days.includes(w.day);
                          return (
                            <button
                              key={w.day}
                              type="button"
                              onClick={() => {
                                const next = active ? days.filter((d) => d !== w.day) : [...days, w.day].sort();
                                setSourceConfig({ ...sourceConfig, active_weekdays: next });
                              }}
                              className={`px-2 py-1 rounded-lg text-[11px] font-semibold border cursor-pointer ${
                                active ? 'bg-navy text-white border-navy' : 'bg-white text-slate-500 border-slate-200'
                              }`}
                            >
                              {w.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={handleSaveConfig}
                      className="px-3 py-1.5 rounded-lg bg-navy text-white text-xs font-semibold cursor-pointer"
                    >
                      Lưu cấu hình
                    </button>
                  </div>
                )}

                {/* Recent Zalo Logs */}
                <div className="space-y-1.5">
                  <h4 className="text-xs font-bold text-navy">Nhật ký gửi Zalo gần đây</h4>
                  {zaloLogs.length === 0 ? (
                    <p className="text-[11px] text-slate-400">Chưa có lịch sử gửi nhắc Zalo.</p>
                  ) : (
                    <div className="space-y-1.5">
                      {zaloLogs.slice(0, 15).map((lg) => (
                        <div key={lg.id} className="rounded-lg border border-slate-200 p-2 text-[11px] bg-white">
                          <div className="flex items-center justify-between font-semibold">
                            <span>
                              {lg.staff_name} ({lg.slot})
                            </span>
                            <span
                              className={
                                lg.status === 'SENT'
                                  ? 'text-emerald-700'
                                  : lg.status === 'FAILED'
                                  ? 'text-rose-600'
                                  : 'text-slate-400'
                              }
                            >
                              {lg.status}
                            </span>
                          </div>
                          <div className="text-[10px] text-slate-400 flex justify-between">
                            <span>{lg.sent_at}</span>
                            <span>
                              Xong: {lg.done_count} • Chưa: {lg.pending_count}
                            </span>
                          </div>
                          {lg.error_message && <p className="text-[10px] text-rose-600 mt-0.5">{lg.error_message}</p>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <BulletinCalendarBlock
            isAdmin={isAdmin}
            adminOwnerFilter={adminOwnerFilter}
            todayStr={todayStr}
            refreshTrigger={calendarRefreshTick}
            onCreateReminderForDate={(dateStr) => openReminderModal(null, null, dateStr)}
            onEditReminder={(rem) => openReminderModal(null, rem)}
            onSelectChecklistDate={(dateStr) => {
              setChecklistDate(dateStr);
              setWorkTab('checklist');
              requestAnimationFrame(() => {
                workspaceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              });
            }}
            onReminderMutated={(deltaPending) => {
              if (typeof deltaPending === 'number') {
                setPendingRemindersCount((c) => Math.max(0, c + deltaPending));
              }
              loadReminders();
              setCalendarRefreshTick((t) => t + 1);
            }}
          />
        </aside>
      </div>

      {/* MODAL 1: TẠO / SỬA NHẮC HẸN */}
      <AccessibleModal
        isOpen={reminderModalOpen}
        onClose={() => setReminderModalOpen(false)}
        ariaLabel={editingReminderId ? 'Chỉnh sửa nhắc hẹn' : 'Tạo nhắc hẹn công việc'}
        contentClassName="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-lg p-5 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-navy flex items-center gap-2">
            <BellRing className="w-4 h-4 text-brand-600" />
            {editingReminderId ? 'Chỉnh sửa nhắc hẹn' : 'Tạo nhắc hẹn công việc'}
          </h3>
          <button
            type="button"
            onClick={() => setReminderModalOpen(false)}
            className="text-xs text-slate-400 hover:text-navy cursor-pointer"
          >
            Đóng
          </button>
        </div>

        {remSourcePost && (
          <div className="rounded-xl bg-brand-50/70 border border-brand-200 px-3 py-2 text-xs text-brand-800">
            Gắn với bản tin của <strong>{remSourcePost.boss_display_name}</strong> ({remSourcePost.posted_at})
          </div>
        )}

        <form onSubmit={handleSaveReminder} className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-navy mb-1">Tiêu đề nhắc hẹn *</label>
            <input
              type="text"
              required
              value={remTitle}
              onChange={(e) => setRemTitle(e.target.value)}
              placeholder="VD: Hoàn thành báo cáo P&L gửi sếp Ann"
              className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-navy mb-1">Ghi chú chi tiết</label>
            <textarea
              rows={2}
              value={remDesc}
              onChange={(e) => setRemDesc(e.target.value)}
              placeholder="Nội dung chi tiết cần nhớ..."
              className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-navy mb-1">Thời gian nhắc *</label>
              <input
                type="datetime-local"
                required
                value={remAt}
                onChange={(e) => setRemAt(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs font-mono"
              />
              <div className="flex flex-wrap gap-1 mt-1.5">
                <button
                  type="button"
                  onClick={() => setRemAt(getTodayPresetTime('11:00'))}
                  className="px-2 py-0.5 rounded bg-slate-100 text-[10px] font-semibold hover:bg-slate-200 cursor-pointer"
                >
                  11:00 hôm nay
                </button>
                <button
                  type="button"
                  onClick={() => setRemAt(getTodayPresetTime('15:00'))}
                  className="px-2 py-0.5 rounded bg-slate-100 text-[10px] font-semibold hover:bg-slate-200 cursor-pointer"
                >
                  15:00 hôm nay
                </button>
                <button
                  type="button"
                  onClick={() => setRemAt(getTodayPresetTime('09:00', 1))}
                  className="px-2 py-0.5 rounded bg-slate-100 text-[10px] font-semibold hover:bg-slate-200 cursor-pointer"
                >
                  09:00 ngày mai
                </button>
              </div>
            </div>

            <div className="space-y-2.5">
              <div>
                <label className="block text-xs font-semibold text-navy mb-1">Mức độ ưu tiên</label>
                <select
                  value={remPriority}
                  onChange={(e) => setRemPriority(e.target.value as any)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs bg-white"
                >
                  <option value="low">Thấp</option>
                  <option value="normal">Bình thường</option>
                  <option value="high">Cao</option>
                  <option value="urgent">Khẩn cấp</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-navy mb-1">Lặp lại định kỳ</label>
                <select
                  value={remRecurrence}
                  onChange={(e) => setRemRecurrence(e.target.value as any)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs bg-white"
                >
                  <option value="none">Không lặp</option>
                  <option value="daily">Hàng ngày</option>
                  <option value="weekly">Hàng tuần</option>
                  <option value="monthly">Hàng tháng</option>
                </select>
              </div>
            </div>
          </div>

          {!editingReminderId && renderAdminMultiAssigneePicker(remOwnerIds, setRemOwnerIds)}

          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 space-y-1.5">
            <p className="text-[11px] font-bold text-navy">Kênh nhắc Zalo Eztech Consultant</p>
            <div className="flex flex-wrap gap-3 text-xs text-slate-700">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" checked={remNotify11h} onChange={(e) => setRemNotify11h(e.target.checked)} />
                Tổng hợp 11:00
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" checked={remNotify15h} onChange={(e) => setRemNotify15h(e.target.checked)} />
                Tổng hợp 15:00
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" checked={remNotifyExact} onChange={(e) => setRemNotifyExact(e.target.checked)} />
                Nhắc đúng giờ hẹn
              </label>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setReminderModalOpen(false)}
              className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer"
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={savingRem}
              className="px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold cursor-pointer disabled:opacity-50"
            >
              {savingRem ? 'Đang lưu...' : editingReminderId ? 'Cập nhật nhắc hẹn' : 'Lưu nhắc hẹn'}
            </button>
          </div>
        </form>
      </AccessibleModal>

      {/* MODAL 2: TẠO CHECKLIST HÀNG NGÀY */}
      <AccessibleModal
        isOpen={checklistModalOpen}
        onClose={() => setChecklistModalOpen(false)}
        ariaLabel="Tạo checklist công việc hàng ngày"
        contentClassName="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-lg p-5 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-navy flex items-center gap-2">
            <CheckSquare className="w-4 h-4 text-emerald-600" />
            Tạo checklist công việc hàng ngày
          </h3>
          <button
            type="button"
            onClick={() => setChecklistModalOpen(false)}
            className="text-xs text-slate-400 hover:text-navy cursor-pointer"
          >
            Đóng
          </button>
        </div>

        {clSourcePost && (
          <div className="rounded-xl bg-emerald-50/70 border border-emerald-200 px-3 py-2 text-xs text-emerald-800">
            Tạo từ bản tin của <strong>{clSourcePost.boss_display_name}</strong> ({clSourcePost.posted_at})
          </div>
        )}

        <form onSubmit={handleSaveChecklist} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold text-navy mb-1">Tên checklist *</label>
              <input
                type="text"
                required
                value={clTitle}
                onChange={(e) => setClTitle(e.target.value)}
                placeholder="VD: Checklist xử lý công việc ngày"
                className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-navy mb-1">Ngày thực hiện</label>
              <input
                type="date"
                value={clDateInput}
                onChange={(e) => setClDateInput(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs font-mono"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-navy mb-1">
              Danh sách đầu việc (mỗi dòng 1 hạng mục)
            </label>
            <textarea
              rows={5}
              value={clItemsText}
              onChange={(e) => setClItemsText(e.target.value)}
              placeholder={'Kiểm tra lead mới sáng nay\nCập nhật tiến độ học viên\nGửi báo cáo cuối ngày'}
              className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
            />
          </div>

          {renderAdminMultiAssigneePicker(clOwnerIds, setClOwnerIds)}

          {isAdmin && (
            <div>
              <label className="block text-xs font-semibold text-navy mb-1">
                Note cho nhân viên (Admin — tuỳ chọn)
              </label>
              <textarea
                rows={2}
                value={clAdminNote}
                onChange={(e) => setClAdminNote(e.target.value)}
                placeholder="VD: Ưu tiên xử lý xong trước 15h hôm nay và báo lại trên nhóm..."
                className="w-full px-3 py-2 rounded-xl border border-amber-200 bg-amber-50/40 text-xs focus:outline-none focus:ring-2 focus:ring-amber-400/30"
              />
            </div>
          )}

          <label className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer bg-slate-50 border border-slate-200 rounded-xl px-3 py-2">
            <input type="checkbox" checked={clRecurring} onChange={(e) => setClRecurring(e.target.checked)} />
            <span>Tự động lặp lại checklist này hàng ngày (tạo mới mỗi ngày)</span>
          </label>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setChecklistModalOpen(false)}
              className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer"
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={savingCl}
              className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold cursor-pointer disabled:opacity-50"
            >
              {savingCl ? 'Đang lưu...' : 'Tạo checklist'}
            </button>
          </div>
        </form>
      </AccessibleModal>

      {/* MODAL 3: A2 — AI TÁCH ĐẦU VIỆC & NHẮC HẸN TỪ BẢN TIN */}
      <AccessibleModal
        isOpen={aiModalOpen}
        onClose={() => setAiModalOpen(false)}
        ariaLabel="AI tách đầu việc từ bản tin"
        contentClassName="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-lg p-5 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-navy flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-600" />
            AI tách đầu việc & gợi ý nhắc hẹn
          </h3>
          <button
            type="button"
            onClick={() => setAiModalOpen(false)}
            className="text-xs text-slate-400 hover:text-navy cursor-pointer"
          >
            Đóng
          </button>
        </div>

        {aiResult?.summary && (
          <div className="rounded-xl bg-purple-50/70 border border-purple-200 px-3 py-2 text-xs text-purple-900">
            <strong>Tóm tắt:</strong> {aiResult.summary}
          </div>
        )}

        <form onSubmit={handleSaveAiExtracted} className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-navy mb-1">Tên checklist</label>
            <input
              type="text"
              value={aiClTitle}
              onChange={(e) => setAiClTitle(e.target.value)}
              className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-navy mb-1">
              Đầu việc AI đề xuất (chỉnh sửa tự do, mỗi dòng 1 việc)
            </label>
            <textarea
              rows={5}
              value={aiClItemsText}
              onChange={(e) => setAiClItemsText(e.target.value)}
              className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs focus:outline-none focus:ring-2 focus:ring-purple-500/20"
            />
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 space-y-2">
            <label className="flex items-center gap-2 text-xs font-semibold text-navy cursor-pointer">
              <input
                type="checkbox"
                checked={aiIncludeReminder}
                onChange={(e) => setAiIncludeReminder(e.target.checked)}
              />
              <span>Tạo kèm Nhắc hẹn Zalo từ bản tin này</span>
            </label>
            {aiIncludeReminder && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                <input
                  type="text"
                  value={aiRemTitle}
                  onChange={(e) => setAiRemTitle(e.target.value)}
                  placeholder="Tiêu đề nhắc hẹn"
                  className="sm:col-span-2 px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white text-xs"
                />
                <input
                  type="datetime-local"
                  value={aiRemAt}
                  onChange={(e) => setAiRemAt(e.target.value)}
                  className="px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-mono"
                />
                <select
                  value={aiRemPriority}
                  onChange={(e) => setAiRemPriority(e.target.value as any)}
                  className="px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white text-xs"
                >
                  <option value="low">Ưu tiên: Thấp</option>
                  <option value="normal">Ưu tiên: Bình thường</option>
                  <option value="high">Ưu tiên: Cao</option>
                  <option value="urgent">Ưu tiên: Khẩn cấp</option>
                </select>
              </div>
            )}
          </div>

          {renderAdminMultiAssigneePicker(aiOwnerIds, setAiOwnerIds)}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setAiModalOpen(false)}
              className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer"
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={savingAi}
              className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold cursor-pointer disabled:opacity-50"
            >
              {savingAi ? 'Đang lưu...' : aiIncludeReminder ? 'Tạo Checklist & Nhắc hẹn' : 'Tạo Checklist'}
            </button>
          </div>
        </form>
      </AccessibleModal>
    </div>
  );
}
