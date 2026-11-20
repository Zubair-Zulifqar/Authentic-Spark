"use client";
import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import {
  getAuth, onIdTokenChanged, signInWithEmailAndPassword, signInWithPopup, GoogleAuthProvider,
  sendPasswordResetEmail, sendEmailVerification, signOut as fbSignOut, type User,
} from "firebase/auth";
import { create } from "zustand";

export const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";

let app: FirebaseApp | null = null;
function fb() {
  if (!app) {
    app = getApps()[0] ?? initializeApp({
      apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
      authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
      projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
      appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
    });
  }
  return getAuth(app);
}

type AuthState = {
  ready: boolean;
  email: string | null;
  emailVerified: boolean;
  devToken: string | null;
  set: (p: Partial<AuthState>) => void;
};

export const useAuth = create<AuthState>((set) => ({
  ready: false, email: null, emailVerified: false, devToken: null,
  set: (p) => set(p),
}));

const DEV_KEY = "spark.devEmail";

export function initAuth() {
  if (AUTH_MODE === "dev") {
    let email: string | null = null;
    try { email = localStorage.getItem(DEV_KEY); } catch { /* storage unavailable */ }
    useAuth.getState().set({ ready: true, email, emailVerified: true, devToken: email ? `dev:${email}` : null });
    return () => {};
  }
  return onIdTokenChanged(fb(), (u: User | null) => {
    useAuth.getState().set({ ready: true, email: u?.email ?? null, emailVerified: !!u?.emailVerified });
  });
}

export async function getToken(): Promise<string | null> {
  if (AUTH_MODE === "dev") return useAuth.getState().devToken;
  return (await fb().currentUser?.getIdToken()) ?? null;
}

export async function signIn(email: string, password: string) {
  if (AUTH_MODE === "dev") {
    try { localStorage.setItem(DEV_KEY, email); } catch { /* ignore */ }
    useAuth.getState().set({ email, devToken: `dev:${email}`, emailVerified: true });
    return;
  }
  await signInWithEmailAndPassword(fb(), email, password);
}

export async function signInWithGoogle() {
  await signInWithPopup(fb(), new GoogleAuthProvider());
}

export async function resetPassword(email: string) {
  await sendPasswordResetEmail(fb(), email);
}

export async function resendVerification() {
  const u = fb().currentUser;
  if (u) await sendEmailVerification(u);
}

export async function signOut() {
  if (AUTH_MODE === "dev") {
    try { localStorage.removeItem(DEV_KEY); } catch { /* ignore */ }
    useAuth.getState().set({ email: null, devToken: null });
    return;
  }
  await fbSignOut(fb());
}
