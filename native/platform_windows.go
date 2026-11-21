package main

import (
	"encoding/base64"
	"golang.org/x/sys/windows"
	"path/filepath"
	"unsafe"
)

var held, presence windows.Handle

func lockProfile(root string) error {
	p, e := windows.UTF16PtrFromString(filepath.Join(root, "client.lock"))
	if e != nil {
		return e
	}
	h, e := windows.CreateFile(p, windows.GENERIC_READ|windows.GENERIC_WRITE, 0, nil, windows.OPEN_ALWAYS, windows.FILE_ATTRIBUTE_NORMAL, 0)
	if e == nil {
		tag, err := windows.UTF16PtrFromString(filepath.Join(root, "native-active.lock"))
		if err != nil {
			windows.CloseHandle(h)
			return err
		}
		presence, err = windows.CreateFile(tag, windows.GENERIC_READ|windows.GENERIC_WRITE, 0, nil, windows.OPEN_ALWAYS, windows.FILE_ATTRIBUTE_NORMAL, 0)
		if err != nil {
			windows.CloseHandle(h)
			return err
		}
		held = h
	}
	return e
}

func unlockProfile() {
	if presence != 0 {
		windows.CloseHandle(presence)
		presence = 0
	}
	if held != 0 {
		windows.CloseHandle(held)
		held = 0
	}
}

func password(protected string) (string, error) {
	if protected == "" {
		return "", nil
	}
	raw, e := base64.StdEncoding.DecodeString(protected)
	if e != nil || len(raw) == 0 {
		return "", windows.ERROR_INVALID_DATA
	}
	in := windows.DataBlob{Size: uint32(len(raw)), Data: &raw[0]}
	var out windows.DataBlob
	if e = windows.CryptUnprotectData(&in, nil, nil, 0, nil, 1, &out); e != nil {
		return "", e
	}
	defer windows.LocalFree(windows.Handle(unsafe.Pointer(out.Data)))
	return string(unsafe.Slice(out.Data, int(out.Size))), nil
}

func protectPassword(plain string) (string, error) {
	if plain == "" {
		return "", nil
	}
	raw := []byte(plain)
	in := windows.DataBlob{Size: uint32(len(raw)), Data: &raw[0]}
	var out windows.DataBlob
	if err := windows.CryptProtectData(&in, nil, nil, 0, nil, 1, &out); err != nil {
		return "", err
	}
	defer windows.LocalFree(windows.Handle(unsafe.Pointer(out.Data)))
	return base64.StdEncoding.EncodeToString(unsafe.Slice(out.Data, int(out.Size))), nil
}
