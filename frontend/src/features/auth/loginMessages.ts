import type { LoginError } from '@/stores/authStore';

/** User-facing Arabic messages. Never expose backend internals. */
export function loginErrorMessage(error: LoginError): string {
  switch (error.code) {
    case 'invalid_credentials':
      return 'اسم المستخدم أو كلمة المرور غير صحيحة.';
    case 'too_many_attempts':
      return error.retryAfterSeconds
        ? `محاولات كثيرة. يرجى المحاولة بعد ${Math.ceil(error.retryAfterSeconds / 60)} دقيقة.`
        : 'محاولات كثيرة. يرجى المحاولة لاحقاً.';
    case 'network':
      return 'تعذر الاتصال بالخادم. تأكد من تشغيله ثم أعد المحاولة.';
    case 'unknown':
      return 'حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.';
  }
}
