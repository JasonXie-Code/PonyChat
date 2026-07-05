import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useSiteConfig } from "../config/SiteConfigContext";
import type { QuizVersion, Side } from "../lib/types";

export interface SessionState {
  gender: string;
  age: string;
  version: QuizVersion | null;
  /** 本次测验抽中的题号及展示顺序（从 72 题池中均衡随机抽取后打乱） */
  quizOrder: number[];
  answers: Record<number, Side>;
  anonId: string;
}

interface SessionContextValue extends SessionState {
  setGender: (v: string) => void;
  setAge: (v: string) => void;
  setVersion: (v: QuizVersion | null) => void;
  setQuizOrder: (ids: number[]) => void;
  setAnswer: (questionId: number, side: Side) => void;
  resetAnswers: () => void;
  resetAll: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const { storageKey, anonIdKey } = useSiteConfig();

  function loadAnonId(): string {
    try {
      let id = localStorage.getItem(anonIdKey);
      if (!id) {
        id = crypto.randomUUID();
        localStorage.setItem(anonIdKey, id);
      }
      return id;
    } catch {
      return "local";
    }
  }

  function loadSession(): Partial<SessionState> {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return {};
      return JSON.parse(raw) as Partial<SessionState>;
    } catch {
      return {};
    }
  }

  function saveSession(s: SessionState) {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          gender: s.gender,
          age: s.age,
          version: s.version,
          quizOrder: s.quizOrder,
          answers: s.answers,
        })
      );
    } catch {
      /* 忽略 */
    }
  }

  const persisted = loadSession();
  const [gender, setGenderState] = useState(persisted.gender ?? "");
  const [age, setAgeState] = useState(persisted.age ?? "");
  const [version, setVersionState] = useState<QuizVersion | null>(
    persisted.version ?? null
  );
  const [quizOrder, setQuizOrderState] = useState<number[]>(
    Array.isArray(persisted.quizOrder) ? persisted.quizOrder : []
  );
  const [answers, setAnswers] = useState<Record<number, Side>>(
    persisted.answers ?? {}
  );
  const anonId = useMemo(() => loadAnonId(), [anonIdKey]);

  const setGender = useCallback((v: string) => {
    setGenderState(v);
  }, []);
  const setAge = useCallback((v: string) => {
    setAgeState(v);
  }, []);
  const setVersion = useCallback((v: QuizVersion | null) => {
    setVersionState(v);
  }, []);
  const setQuizOrder = useCallback((ids: number[]) => {
    setQuizOrderState(ids);
  }, []);

  const setAnswer = useCallback((questionId: number, side: Side) => {
    setAnswers((prev: Record<number, Side>) => ({ ...prev, [questionId]: side }));
  }, []);

  const resetAnswers = useCallback(() => setAnswers({}), []);

  const resetAll = useCallback(() => {
    setGenderState("");
    setAgeState("");
    setVersionState(null);
    setQuizOrderState([]);
    setAnswers({});
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* 忽略 */
    }
  }, [storageKey]);

  const state: SessionState = useMemo(
    () => ({ gender, age, version, quizOrder, answers, anonId }),
    [gender, age, version, quizOrder, answers, anonId]
  );

  useEffect(() => {
    saveSession(state);
  }, [state]);

  const value = useMemo(
    () => ({
      ...state,
      setGender,
      setAge,
      setVersion,
      setQuizOrder,
      setAnswer,
      resetAnswers,
      resetAll,
    }),
    [
      state,
      setGender,
      setAge,
      setVersion,
      setQuizOrder,
      setAnswer,
      resetAnswers,
      resetAll,
    ]
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession needs SessionProvider");
  return ctx;
}
