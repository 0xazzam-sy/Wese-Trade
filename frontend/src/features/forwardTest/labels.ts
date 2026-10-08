import type { ForwardStatus } from '@/types/forwardTest';

/** Arabic product wording. Never: موثوق / مضمون / عالي الدقة / نسبة نجاح. */
export const FORWARD_STATUS_AR: Record<ForwardStatus, string> = {
  forward_testing: 'متابعة مباشرة',
  paused: 'متوقف',
  stopped: 'متوقف',
  passed_forward_test: 'تحققت شروط الأداء',
  failed_forward_test: 'لم تتحقق شروط الأداء',
};

export const FORWARD_DISCLAIMER = 'الإشارات تحليلية وليست توصيات مضمونة.';

export const HEALTH_AR: Record<string, string> = {
  running: 'يعمل',
  paused: 'متوقف مؤقتاً',
  degraded: 'متدهور',
  stopped: 'متوقف',
};

export const VERDICT_AR: Record<string, string> = {
  INSUFFICIENT_SAMPLE: 'عينة غير كافية بعد',
  CONTINUE: 'مستمر — لم تتحقق كل الشروط',
  PASS_CRITERIA_MET: 'تحققت شروط النجاح',
  FAIL_CRITERIA_MET: 'تحققت شروط الفشل',
};

export function fmtR(v: number | null | undefined, digits = 3): string {
  if (v == null) return '--';
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}R`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  return v == null ? '--' : v.toFixed(digits);
}

export function fmtPct(v: number | null | undefined): string {
  return v == null ? '--' : `${(v * 100).toFixed(1)}%`;
}

export function statusTone(status: string | undefined): string {
  if (status === 'forward_testing') return 'border-accent/40 bg-accent/10 text-accent';
  if (status === 'passed_forward_test') return 'border-bull/40 bg-bull/10 text-bull';
  if (status === 'failed_forward_test') return 'border-bear/40 bg-bear/10 text-bear';
  return 'border-warning/40 bg-warning/10 text-warning';
}
