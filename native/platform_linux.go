package main

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
)

var held *os.File

func lockProfile(root string) error {
	f, e := os.OpenFile(filepath.Join(root, "client.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return e
	}
	if e = syscall.Flock(int(f.Fd()), syscall.LOCK_NB|syscall.LOCK_EX); e != nil {
		f.Close()
		return e
	}
	held = f
	return nil
}

func unlockProfile() {
	if held != nil {
		held.Close()
		held = nil
	}
}

func password(p string) (string, error) {
	if p != "" {
		return "", fmt.Errorf("Windows credential on Linux")
	}
	return "", nil
}

func protectPassword(plain string) (string, error) {
	if plain != "" {
		return "", fmt.Errorf("Windows credentials cannot be created on Linux")
	}
	return "", nil
}
