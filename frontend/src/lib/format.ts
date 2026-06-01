export const formatBarWidth = (value: number, max: number) =>
  `${Math.max((value / Math.max(max, 1)) * 100, 4)}%`;

export function formatDatasetLabel(name: string): string {
  if (name === 'RU_Dataset_cleaned') return '微博舆情样本';
  if (name === 'russia_ukraine_conflict') return 'ACLED 冲突事件';
  return name;
}
