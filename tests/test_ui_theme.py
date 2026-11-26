"""Shared theme remains stable when multiple desktop windows use it."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'))
from ootrr_triforce.ui_theme import COLORS, apply_theme, draw_brand, set_window_icon


class SharedThemeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_dialog_application_preserves_existing_styles_and_widget_state(self):
        style=apply_theme(self.root)
        style.configure('Private.TLabel',foreground='#123456')
        entry=ttk.Entry(self.root)
        entry.insert(0,'unchanged room address')
        entry.state(['disabled'])
        child=tk.Toplevel(self.root)
        child.withdraw()
        self.assertIs(apply_theme(child),style)
        self.assertEqual(style.lookup('Private.TLabel','foreground'),'#123456')
        self.assertEqual(entry.get(),'unchanged room address')
        self.assertIn('disabled',entry.state())
        self.assertEqual(child.cget('background'),COLORS['bg'])

    def test_form_controls_keep_readonly_text_and_visible_keyboard_focus(self):
        style=apply_theme(self.root)
        for control in ('TEntry','TCombobox','TSpinbox'):
            self.assertEqual(style.lookup(control,'foreground',('readonly',)),COLORS['text'])
            self.assertEqual(style.lookup(control,'foreground',('disabled',)),COLORS['muted'])
            self.assertEqual(style.lookup(control,'bordercolor',('focus',)),COLORS['gold'])
        self.assertEqual(style.lookup('App.Primary.TButton','foreground'),COLORS['bg'])
        self.assertEqual(style.lookup('App.Primary.TButton','background'),COLORS['gold'])
        self.assertEqual(style.lookup('App.Primary.TButton','focuscolor'),COLORS['bg'])
        self.assertEqual(style.lookup('App.Card.TCheckbutton','background',('active',)),COLORS['surface'])
        self.assertEqual(style.lookup('App.Card.TRadiobutton','background',('active',)),COLORS['surface'])

    def test_classic_widgets_and_combobox_popup_use_the_shared_palette(self):
        apply_theme(self.root)
        for widget in (tk.Text(self.root),tk.Listbox(self.root)):
            self.assertEqual(widget.cget('background'),COLORS['elevated'])
            self.assertEqual(widget.cget('foreground'),COLORS['text'])
            self.assertEqual(widget.cget('selectbackground'),COLORS['gold'])

    def test_title_uses_its_style_font_instead_of_a_global_widget_override(self):
        apply_theme(self.root)
        title=ttk.Label(self.root,text='Archipelago',style='App.Title.TLabel')
        body=ttk.Label(self.root,text='Archipelago',style='App.Card.TLabel')
        self.assertGreater(title.winfo_reqheight(),body.winfo_reqheight()*1.5)

    def test_vector_instances_fit_their_bounds_without_changing_other_artwork(self):
        apply_theme(self.root)
        canvas=tk.Canvas(self.root,width=200,height=100)
        original=canvas.create_line(0,0,1,1)
        first=draw_brand(canvas,0,0,80)
        second=draw_brand(canvas,100,10,60)
        self.assertTrue(first and second)
        self.assertTrue(set(first).isdisjoint(second))
        for item in second:
            coords=canvas.coords(item)
            self.assertTrue(all(100<=value<=160 for value in coords[::2]))
            self.assertTrue(all(10<=value<=70 for value in coords[1::2]))
        for item in first:canvas.delete(item)
        self.assertTrue(canvas.type(original))
        self.assertTrue(all(canvas.type(item) for item in second))
        self.assertEqual(draw_brand(canvas,0,0,0),[])

    def test_icon_is_cached_across_windows_without_allocating_duplicate_images(self):
        apply_theme(self.root)
        if not set_window_icon(self.root):
            self.skipTest('Optional application icon unavailable')
        image=self.root._ootrr_app_icon
        images=set(self.root.tk.call('image','names'))
        dialog=tk.Toplevel(self.root)
        dialog.withdraw()
        self.assertTrue(set_window_icon(dialog))
        self.assertIs(self.root._ootrr_app_icon,image)
        self.assertEqual(set(self.root.tk.call('image','names')),images)
        self.root.update_idletasks()

    def test_closing_before_idle_cancels_only_its_own_titlebar_callback(self):
        apply_theme(self.root)
        errors=[]
        self.root.tk.createcommand('bgerror',errors.append)
        self.addCleanup(lambda:self.root.tk.deletecommand('bgerror'))
        dialog=tk.Toplevel(self.root)
        dialog.withdraw()
        set_window_icon(dialog)
        unrelated=[]
        self.root.after_idle(lambda:unrelated.append(True))
        dialog.destroy()
        self.root.update()
        self.assertEqual(errors,[])
        self.assertEqual(unrelated,[True])


if __name__=='__main__':unittest.main()
