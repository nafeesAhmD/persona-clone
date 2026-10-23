import type { CloneStatus, ResponseLength, Visibility } from "@/types/clone";

// Choice lists for the clone form. Languages and styles are stored as plain text,
// so adding an option here needs no backend change.

export const LANGUAGES = ["English", "Urdu", "Roman Urdu"];

export const COMMUNICATION_STYLES = ["Friendly", "Professional", "Simple", "Detailed", "Casual"];

export const RESPONSE_LENGTHS: { value: ResponseLength; label: string; description: string }[] = [
  { value: "short", label: "Short", description: "A few sentences" },
  { value: "medium", label: "Medium", description: "A short paragraph" },
  { value: "detailed", label: "Detailed", description: "Thorough answers with examples" },
];

export const VISIBILITIES: { value: Visibility; label: string; description: string }[] = [
  { value: "private", label: "Private", description: "Only you can access it." },
  { value: "public", label: "Public", description: "Anyone can find it in the clone list and chat with it." },
  { value: "unlisted", label: "Unlisted", description: "Not listed. Anyone with the direct chat link can use it." },
];

export const STATUSES: { value: CloneStatus; label: string; description: string }[] = [
  { value: "active", label: "Active", description: "Ready to chat." },
  { value: "draft", label: "Draft", description: "Only you can chat with it while you set it up." },
  { value: "disabled", label: "Disabled", description: "Chat is turned off for everyone. You can still edit it." },
];

export const labelFor = <T extends string>(options: { value: T; label: string }[], value: T): string =>
  options.find((option) => option.value === value)?.label ?? value;
