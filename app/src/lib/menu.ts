export interface MenuItem {
  label: string;
  action?: () => void;
  disabled?: boolean;
  /** Shown beside the item, e.g. the milestone that brings a planned feature. */
  note?: string;
  separator?: boolean;
}
