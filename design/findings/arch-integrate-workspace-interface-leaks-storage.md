---
kind: question
station: interface
source: critic
by: interface-leaks-storage
subject: arch.integrate.workspace
digest: d4176cd9e6d2
evidence: Workspace.design_dir(self) -> Path
hint: Remove design_dir from the public interface and give callers domain-level access (design(), design_files(), write()). Any caller that needs a location should get a ProjectPath or DesignPath value, not a filesystem Path.
---
The workspace hides the filesystem layout, but this method hands callers the raw directory where design files are kept. Callers can then read or write there directly, which ties them to the layout and gets around the atomic write in AC2.
