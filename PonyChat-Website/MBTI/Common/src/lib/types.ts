export type QuizVersion = "q12" | "q36";
export type Side = "L" | "R";

export interface QuestionItem {
  id: number;
  axis: "EI" | "SN" | "TF" | "JP";
  optionLeftPole: string;
  optionRightPole: string;
  text: string;
  optionLeft: string;
  optionRight: string;
}

export interface QuestionBank {
  schemaVersion: string;
  items: QuestionItem[];
}
