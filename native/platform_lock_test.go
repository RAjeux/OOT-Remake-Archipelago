package main

import "testing"

func TestProfileLockReleaseAndReacquire(t *testing.T) {
	root := t.TempDir()
	if err := lockProfile(root); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(unlockProfile)
	if err := lockProfile(root); err == nil {
		t.Fatal("a second owner acquired the profile")
	}
	// Failed startup must release every handle, including Windows presence.
	unlockProfile()
	if err := lockProfile(root); err != nil {
		t.Fatalf("profile was not released for a startup retry: %v", err)
	}
	unlockProfile()
	// Cleanup is idempotent and leaves the next game/setup free to start.
	unlockProfile()
	if err := lockProfile(root); err != nil {
		t.Fatalf("idempotent cleanup retained a profile handle: %v", err)
	}
}
