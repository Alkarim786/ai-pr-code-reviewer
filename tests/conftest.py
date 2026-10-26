import pytest

SAMPLE_DIFF = """diff --git a/app/x.py b/app/x.py
--- a/app/x.py
+++ b/app/x.py
@@ -1,3 +1,5 @@
 import os
+import sys

 def f():
+    return os.getcwd()
     pass
diff --git a/old.py b/old.py
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
diff --git a/new.py b/new.py
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+a = 1
+b = 2
"""


@pytest.fixture
def sample_diff():
    return SAMPLE_DIFF
