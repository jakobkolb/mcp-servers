package bridge

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Static guard for "no code path can send a WhatsApp message": none of the bridge's own
// code may call a whatsmeow method that sends, uploads, edits or marks anything.
var forbidden = map[string]bool{
	"SendMessage": true, "SendChatPresence": true, "SendPresence": true, "SendFBMessage": true,
	"Upload": true, "UploadReader": true, "UploadNewsletter": true,
	"Download": true, "DownloadAny": true, "DownloadToFile": true, "DownloadThumbnail": true,
	"MarkRead": true, "SendReceipt": true, "BuildEdit": true, "BuildRevoke": true,
	"BuildReaction": true, "RevokeMessage": true, "SetStatusMessage": true, "SetPassive": true,
	"CreateGroup": true, "LeaveGroup": true, "SetGroupName": true, "UpdateGroupParticipants": true,
}

func TestNoSendingCodePaths(t *testing.T) {
	roots := []string{".", "../../cmd"}
	checked := 0
	for _, root := range roots {
		err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
			if err != nil || info.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
				return err
			}
			f, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
			if err != nil {
				return err
			}
			checked++
			ast.Inspect(f, func(n ast.Node) bool {
				if sel, ok := n.(*ast.SelectorExpr); ok && forbidden[sel.Sel.Name] {
					t.Errorf("%s: forbidden call .%s", path, sel.Sel.Name)
				}
				return true
			})
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	if checked < 4 {
		t.Fatalf("guard only inspected %d files; path layout changed?", checked)
	}
}
