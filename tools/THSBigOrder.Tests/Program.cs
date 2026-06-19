using System;
using THSBigOrder;

internal static class Program
{
    [STAThread]
    private static int Main()
    {
        Run("Assembly and provider use THSBigOrder names", () =>
        {
            AssertEqual("THSBigOrder", typeof(THSBigOrderDataProvider).Assembly.GetName().Name, "assembly");
            AssertEqual("THSBigOrder", typeof(THSBigOrderDataProvider).Namespace, "namespace");
        });
        return Environment.ExitCode;
    }

    private static void Run(string name, Action test)
    {
        try
        {
            test();
            Console.WriteLine("PASS " + name);
        }
        catch (Exception error)
        {
            Environment.ExitCode = 1;
            Console.Error.WriteLine("FAIL " + name + ": " + error.Message);
        }
    }

    private static void AssertEqual<T>(T expected, T actual, string label)
    {
        if (!Equals(expected, actual))
        {
            throw new InvalidOperationException(label + " expected " + expected + ", actual " + actual);
        }
    }
}
