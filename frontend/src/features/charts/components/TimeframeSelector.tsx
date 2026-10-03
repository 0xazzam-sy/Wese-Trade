import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { TIMEFRAMES, type Timeframe } from '@/types/market';

const OPTIONS = TIMEFRAMES.map((tf) => ({ value: tf.value, label: tf.label, title: tf.value }));

export function TimeframeSelector({
  value,
  onChange,
}: {
  value: Timeframe;
  onChange: (value: Timeframe) => void;
}) {
  return (
    <SegmentedControl
      ariaLabel="الإطار الزمني"
      size="sm"
      value={value}
      options={OPTIONS}
      onChange={onChange}
    />
  );
}
