import { ApiError } from '@/lib/http';

export const PASSWORD_HINT =
  '12 حرفاً على الأقل، بلا مسافات في البداية أو النهاية، وغير متكررة الأحرف.';

/** Arabic messages for account create / update / setup errors (never backend internals). */
export function userErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.';
  if (error.isNetworkError) return 'تعذر الاتصال بالخادم المحلي.';
  switch (error.code) {
    case 'weak_password':
      return `كلمة المرور ضعيفة: ${PASSWORD_HINT}`;
    case 'invalid_username':
      return 'اسم المستخدم من 3 إلى 64 حرفاً: أحرف إنجليزية وأرقام و _ . - فقط.';
    case 'username_taken':
      return 'اسم المستخدم مستخدم بالفعل.';
    case 'last_admin':
      return 'يجب أن يبقى مدير نظام واحد نشط على الأقل.';
    case 'setup_complete':
      return 'تم إعداد الحساب الأول مسبقاً. سجّل الدخول.';
    case 'too_many_attempts':
      return 'محاولات كثيرة. يرجى المحاولة لاحقاً.';
    default:
      return 'تعذر حفظ التغييرات. تحقق من البيانات وأعد المحاولة.';
  }
}
