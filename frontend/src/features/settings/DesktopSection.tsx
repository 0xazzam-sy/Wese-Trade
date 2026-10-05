import { useMutation } from '@tanstack/react-query';
import { Download, FolderOpen, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { desktop, isDesktop, type UpdateInfo } from '@/lib/desktop';
import type { RuntimeInfo } from '@/types/system';

import { Row, Section } from './Section';

/** App / installation info. Desktop-only actions are hidden in the browser. */
export function DesktopSection({ runtime }: { runtime: RuntimeInfo | undefined }) {
  const inDesktop = isDesktop();
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const check = useMutation({
    mutationFn: desktop.checkForUpdates,
    onSuccess: (info) => {
      setUpdate(info);
      setMessage(
        !info.configured
          ? 'التحديثات غير مهيأة في هذا الإصدار.'
          : info.available
            ? null
            : 'أنت تستخدم أحدث إصدار.',
      );
    },
    onError: () => {
      setMessage('تعذر التحقق من التحديثات (قد لا يتوفر اتصال بالإنترنت).');
    },
  });
  const install = useMutation({
    mutationFn: desktop.installUpdate,
    onError: () => {
      setMessage('تعذر تثبيت التحديث. لم يتغير شيء في بياناتك.');
    },
  });
  const open = (fn: () => Promise<unknown>) => () => {
    fn().catch(() => {
      setMessage('تعذر فتح المجلد.');
    });
  };
  return (
    <Section id="app" title="التطبيق">
      <Row label="إصدار Wese Trade">
        <span className="ns-ltr ns-num" data-testid="app-version">
          {runtime?.app_version ?? '--'}
        </span>
      </Row>
      <Row label="وضع التشغيل">
        {runtime?.mode === 'desktop' ? 'تطبيق سطح المكتب' : 'المتصفح (تطوير)'}
      </Row>
      {runtime?.paths && (
        <>
          <Row label="مجلد البيانات">
            <span className="ns-ltr text-2xs break-all">{runtime.paths.data}</span>
          </Row>
          <Row label="مجلد السجلات">
            <span className="ns-ltr text-2xs break-all">{runtime.paths.logs}</span>
          </Row>
        </>
      )}
      {inDesktop && (
        <div className="mt-3 flex flex-wrap gap-2" data-testid="desktop-actions">
          <Button onClick={open(desktop.openDataFolder)}>
            <FolderOpen className="size-4" />
            فتح مجلد البيانات
          </Button>
          <Button onClick={open(desktop.openLogsFolder)}>
            <FolderOpen className="size-4" />
            فتح مجلد السجلات
          </Button>
          <Button
            disabled={check.isPending}
            onClick={() => {
              check.mutate();
            }}
          >
            <RefreshCw className="size-4" />
            التحقق من التحديثات
          </Button>
        </div>
      )}
      {update?.available && (
        <div
          className="border-accent/40 bg-accent/5 mt-3 rounded-lg border p-3 text-sm"
          data-testid="update-available"
        >
          <p className="font-medium">
            يتوفر إصدار جديد: <span className="ns-ltr">{update.version}</span> (الحالي{' '}
            <span className="ns-ltr">{update.current_version}</span>)
          </p>
          {update.notes && (
            <p className="text-fg-muted mt-1 text-xs whitespace-pre-line">{update.notes}</p>
          )}
          <p className="text-fg-subtle text-2xs mt-1">
            قبل التثبيت تُحفظ البيانات وتُغلق الخدمات بأمان؛ قاعدة البيانات لا تُمس.
          </p>
          <div className="mt-2 flex gap-2">
            <Button
              variant="primary"
              disabled={install.isPending}
              onClick={() => {
                install.mutate();
              }}
            >
              <Download className="size-4" />
              تنزيل وتثبيت
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setUpdate(null);
              }}
            >
              لاحقاً
            </Button>
          </div>
        </div>
      )}
      {message && <p className="text-fg-muted mt-2 text-xs">{message}</p>}
    </Section>
  );
}
