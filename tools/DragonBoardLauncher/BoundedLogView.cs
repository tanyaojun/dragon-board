namespace DragonBoardLauncher;

internal sealed class BoundedLogView
{
    private readonly int _maxLines;
    private readonly Queue<string> _lines = new();
    private bool _trimRequired;

    public BoundedLogView(int maxLines)
    {
        _maxLines = maxLines;
    }

    public void Append(TextBox textBox, string line)
    {
        _lines.Enqueue(line);
        while (_lines.Count > _maxLines)
        {
            _lines.Dequeue();
            _trimRequired = true;
        }

        if (_trimRequired)
        {
            textBox.Lines = _lines.ToArray();
            _trimRequired = false;
        }
        else
        {
            textBox.AppendText(line + Environment.NewLine);
        }

        textBox.SelectionStart = textBox.TextLength;
        textBox.ScrollToCaret();
    }
}
